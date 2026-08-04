---
layout: post
title: "Rubyの遅延ロードと定数の自動読み込みが、本番環境で予期しない初期化順序を引き起こす理由──Zeitwerkの設定と運用判断"
date: 2026-08-04
categories: tech-tips
tags: ["Ruby", "Rails", "Zeitwerk", "オートローダー", "本番環境"]
author: OpenWorks
---

## 開発環境では動くのに、本番環境で初期化エラーが出る現象

Rails アプリケーションを開発している最中に、こんな経験をしたことはありませんか。

開発環境では何の問題もなく動いているのに、本番環境にデプロイした直後に初期化エラーが出て、アプリケーションが立ち上がらない。エラーログを見ると「定数が見つからない」「初期化順序が違う」といったメッセージが並んでいる。

原因を調べていくと、実は Zeitwerk（Rails 6 以降のデフォルトオートローダー）の動作が、開発環境と本番環境で異なっていたということに気づきます。

この問題は、定数の遅延ロードと自動読み込みの仕組みを理解していないと、何度も引っかかります。特に小規模なチームで複数のプロジェクトを回している場合、各プロジェクトの設定が異なっていたり、本番環境だけ特殊な条件になっていたりすることで、問題が顕在化しやすくなります。

## Zeitwerk の動作が環境で異なる理由

Zeitwerk は、ファイルシステム上のクラス定義を、ファイルパスに基づいて自動的に Ruby の定数にマップするオートローダーです。Rails 6 以降、Sprockets（旧来のオートローダー）に代わって標準になりました。

### 開発環境では「遅延ロード」が基本

開発環境では、Zeitwerk は遅延ロードモードで動作します。つまり、定数が実際に参照されるまで、ファイルをロードしません。

```ruby
# config/environments/development.rb
config.cache_classes = false  # 開発環境のデフォルト
```

この設定では、`User` クラスが最初に参照されるまで、`app/models/user.rb` はメモリにロードされません。開発中にコードを編集して保存すると、次のリクエスト時に新しい定義が読み込まれます。

### 本番環境では「先読み」が必須

一方、本番環境では状況が異なります。

```ruby
# config/environments/production.rb
config.cache_classes = true   # 本番環境のデフォルト
```

`cache_classes = true` の場合、アプリケーション起動時に **すべての定数を事前にロード** する必要があります。これは `eager_load_paths` で指定されたディレクトリ以下のファイルが、起動時に一括ロードされるということです。

ここで問題が起こります。開発環境では遅延ロードなので気づかなかった **初期化順序の問題** が、本番環境の先読みで一気に露呈するのです。

## 初期化順序が狂う具体的なシーン

現場で見かけるパターンをいくつか挙げます。

### パターン1: モジュール定義の順序依存

```ruby
# app/models/concerns/timestamps.rb
module Timestamps
  extend ActiveSupport::Concern
  included do
    before_save :set_timestamps
  end
end

# app/models/user.rb
class User < ApplicationRecord
  include Timestamps  # ← Timestamps が先に読み込まれていることを前提
end
```

開発環境では、`User` を参照する際に必要なファイルが順番に読み込まれます。しかし本番環境で先読みが走る際、ファイルシステムの読み込み順序が異なると、`Timestamps` がまだ定義されていない状態で `User` がロードされることがあります。

### パターン2: 初期化処理内での定数参照

```ruby
# config/initializers/setup.rb
ALLOWED_MODELS = [User, Post, Comment].freeze

# app/models/user.rb
class User < ApplicationRecord
  # ...
end
```

initializer が先に実行され、その時点で `User` がまだ読み込まれていないと、`NameError` が発生します。

### パターン3: クラス変数やクラスメソッドでの初期化

```ruby
# app/models/config.rb
class Config
  SETTINGS = {
    api_key: ENV['API_KEY'],
    timeout: ENV['TIMEOUT'].to_i
  }.freeze
end

# app/services/api_client.rb
class ApiClient
  def initialize
    @timeout = Config::SETTINGS[:timeout]  # ← Config が先に読まれていることを前提
  end
end
```

## 本番環境で起きやすい落とし穴

### eager_load_paths の設定が不完全

デフォルトでは `eager_load_paths` は `app/` 配下の主要ディレクトリのみです。

```ruby
# config/application.rb
config.eager_load_paths += %W(
  #{config.root}/app/models
  #{config.root}/app/controllers
  #{config.root}/app/services
)
```

もし新しいディレクトリ（例えば `app/validators/` や `app/decorators/`）を追加した場合、本番環境での先読み対象に含まれていないと、遅延ロードに頼ることになります。開発環境では動くが、本番環境で初期化タイミングが変わるリスクが生じます。

### Zeitwerk の strict_loading が有効な場合

Rails 7 以降、`config.autoloader = :zeitwerk` 下で `config.eager_load = true` を設定すると、Zeitwerk は strict_loading モードで動作します。このモードでは、定数の参照順序が厳密にチェックされ、予期しない初期化順序がより顕著に現れます。

## 設定と運用の現実的な対策

### 1. 開発環境で本番同等の先読みを試す

最も確実な対策は、開発環境でも本番環境と同じ先読み動作をテストすることです。

```ruby
# config/environments/development.rb
config.cache_classes = true
config.eager_load = true
```

これにより、開発環境で起動時に初期化エラーが発生するかどうかを確認できます。ただし、コード編集後のリロードが効かなくなるため、本格的なデバッグ時のみ有効にするのが実用的です。

### 2. initializer の実行順序を明示的に制御

initializer ファイルの名前で実行順序を制御します。

```
config/initializers/
  ├── 01_load_constants.rb      # 定数定義を先に読む
  ├── 02_setup_config.rb        # 設定初期化
  └── 03_background_jobs.rb     # バックグラウンドジョブ
```

数字プレフィックスを使うことで、実行順序を明示的にします。

### 3. require の明示的な指定

どうしても初期化順序が複雑な場合は、遅延ロードに頼らず明示的に require します。

```ruby
# config/application.rb
require_relative '../app/models/config'
require_relative '../app/services/base_service'
```

ただし、これは保守性を低下させるため、最後の手段です。

### 4. 定数の定義を遅延させる

initializer 内で定数参照が必要な場合、その定数を遅延評価する設計に変更します。

```ruby
# config/initializers/setup.rb
def allowed_models
  @allowed_models ||= [User, Post, Comment]
end

# 使用側
allowed_models.each { |model| register(model) }
```

メソッドの遅延評価により、定数が実際に必要なタイミングで読み込まれます。

## 本番環境でのデプロイ前チェック

実装後、本番環境へのデプロイ前に以下を確認します。

- **起動テスト**: `rails server` または `rails console` を実行し、初期化エラーが出ないか確認
- **ログ確認**: アプリケーション起動ログに警告がないか確認
- **段階的デプロイ**: いきなり全トラフィックを流さず、カナリアデプロイで検証

特に、既存のプロジェクトに新しいディレクトリやモジュールを追加した場合は、必ず本番環境での起動テストを実施してください。

## 向かないケースと判断基準

Zeitwerk の先読みが適切に機能しない場合もあります。

- **動的な定数生成**: 実行時に定数を動的に生成している場合、Zeitwerk の静的な解析では追いつきません
- **複雑な条件分岐**: 環境変数や外部設定に基づいて定数が変わる場合、先読みの恩恵が薄れます
- **レガシーコード**: 古い Rails バージョンから移行した場合、定数参照の依存関係が複雑に絡んでいることがあります

こうした場合は、いっそ明示的な require に切り替えるか、定数参照の設計を見直すことを検討してください。

## まとめ

Zeitwerk の遅延ロードと先読みの違いは、開発環境と本番環境で初期化順序を変えます。開発環境では気づかない問題が本番環境で露呈するのは、この仕組みを理解していないからです。

対策の基本は、開発環境で本番同等の先読みをテストすること、initializer の実行順序を明示すること、そして複雑な初期化依存関係を避けることです。小規模なチームほど、こうした環境差異は見落としやすいので、デプロイ前のチェックリストに「本番環境での起動テスト」を組み込むことをお勧めします。
