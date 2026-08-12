---
layout: post
title: "Ruby の String encoding が API レスポンスで暗黙的に変換されると、クライアント側の JSON パースが失敗する──国際化対応の実装落とし穴"
date: 2026-08-12
categories: tech-tips
tags: ["Ruby", "API設計", "文字エンコーディング", "国際化対応", "JSON処理"]
author: OpenWorks
---

## 現場で起きている問題

API サーバーを Ruby で実装している場合、データベースから取得した文字列や外部サービスからの応答を JSON として返す際に、文字エンコーディングの扱いが思わぬ形で影響することがあります。特に国際化対応を進めている環境では、以下のような現象が報告されやすいです。

- クライアント側で JSON をパースしようとすると、特定の言語の文字列が含まれた場合だけ失敗する
- 開発環境では正常に動作するが、本番環境だけ問題が発生する
- 同じエンドポイントでも、リクエストの内容によってレスポンスの文字エンコーディングが変わる

これらは、Ruby の String オブジェクトが持つ encoding 属性と、Rails の JSON シリアライザーの動作が完全に同期していないために起こります。見た目には「正常な JSON」が返されているのに、クライアント側で期待と異なる挙動をするため、デバッグが難しくなります。

## エンコーディング属性が暗黙的に変わる仕組み

Ruby の String オブジェクトは、作成される際に encoding 属性を持ちます。データベースから取得した文字列、API レスポンスから得た文字列、コード内で直接定義した文字列──それぞれ異なる encoding を持つ可能性があります。

```ruby
# データベースから取得（通常は UTF-8）
name_from_db = "山田太郎"
puts name_from_db.encoding  # => #<Encoding:UTF-8>

# 外部 API から取得（API 側の指定に依存）
response_body = Net::HTTP.get_response(uri).body
puts response_body.encoding  # => #<Encoding:ASCII-8BIT> の可能性

# コード内で直接定義
literal_string = "test"
puts literal_string.encoding  # => #<Encoding:UTF-8>
```

問題は、これらの文字列を Hash に入れて JSON に変換する際に、Rails の JSON エンコーダーが各 String の encoding 属性を参照し、暗黙的な変換を試みることです。特に ASCII-8BIT（バイナリ）と判定された文字列は、JSON エンコード時に予期しない形で処理されることがあります。

## データベース接続設定と encoding の関係

多くの場合、問題の根本は Rails の database.yml や接続設定にあります。

```yaml
# config/database.yml
production:
  adapter: mysql2
  host: localhost
  database: myapp_prod
  encoding: utf8mb4
  # ← これが明示されていないと、MySQL のデフォルト設定に依存
```

MySQL を使用している場合、接続時に encoding を明示しないと、サーバー側の character_set_client 設定に従います。これが latin1 や utf8（3バイト版）に設定されていると、データベースから返される文字列は期待と異なる encoding 属性を持つようになります。

PostgreSQL の場合でも、client_encoding が明示されていないと、サーバー側の設定に依存します。

## JSON レスポンスで失敗する実装パターン

以下のようなコントローラーの実装を考えてみます。

```ruby
class ProductsController < ApplicationController
  def show
    product = Product.find(params[:id])
    
    # データベースから取得した属性をそのまま JSON に
    render json: {
      id: product.id,
      name: product.name,
      description: product.description
    }
  end
end
```

一見問題がないように見えますが、product.name と product.description が異なる encoding 属性を持っていた場合、JSON エンコード時に以下が起こります。

1. Rails の JSON エンコーダーが各 String を走査
2. ASCII-8BIT と判定された文字列は、エスケープ処理が異なる可能性
3. クライアント側で受け取った JSON が、期待と異なる形式に

特に複数のデータソース（データベース、キャッシュ、外部 API）から値を集約する場合、encoding がばらばらになりやすいです。

## 実装上の回避策

### 1. 明示的な encoding 統一

最も確実な方法は、レスポンスを生成する直前に、すべての文字列を UTF-8 に統一することです。

```ruby
class ProductsController < ApplicationController
  def show
    product = Product.find(params[:id])
    
    render json: {
      id: product.id,
      name: product.name.force_encoding('UTF-8').encode('UTF-8'),
      description: product.description.force_encoding('UTF-8').encode('UTF-8')
    }
  end
end
```

ただし、`force_encoding` は encoding 属性を変更するだけで、実際のバイト列は変わりません。既に壊れたバイト列の場合、これだけでは不十分です。

より安全なのは、encoding と同時に invalid 文字を処理することです。

```ruby
def safe_encode_utf8(string)
  return string if string.encoding.name == 'UTF-8'
  
  # 既に UTF-8 の場合はそのまま
  string.force_encoding('UTF-8').encode('UTF-8', invalid: :replace, undef: :replace, replace: '?')
end
```

### 2. データベース接続設定の確認と統一

Rails アプリケーションの起動時に、接続設定を明示的に指定します。

```yaml
# config/database.yml
production:
  adapter: mysql2
  host: localhost
  database: myapp_prod
  username: <%= ENV['DB_USER'] %>
  password: <%= ENV['DB_PASSWORD'] %>
  encoding: utf8mb4
  charset: utf8mb4
  collation: utf8mb4_unicode_ci
```

PostgreSQL の場合：

```yaml
production:
  adapter: postgresql
  host: localhost
  database: myapp_prod
  username: <%= ENV['DB_USER'] %>
  password: <%= ENV['DB_PASSWORD'] %>
  encoding: UTF8
```

### 3. 外部 API からの応答を安全に扱う

外部 API から取得したレスポンスは、encoding 属性が不定です。即座に UTF-8 に統一します。

```ruby
def fetch_external_data(url)
  response = Net::HTTP.get_response(URI(url))
  body = response.body
  
  # encoding を統一してから使用
  body.force_encoding('UTF-8').encode('UTF-8', invalid: :replace, undef: :replace)
end
```

## 運用時の監視と対応

本番環境では、以下の対策を講じておくと、問題が発生した際の対応が容易になります。

- **ログに encoding 情報を記録する**: 問題が起きた際、どの段階で encoding が変わったかを特定できます
- **API レスポンスのサニタイゼーション層を用意する**: すべての JSON レスポンスを一箇所で処理し、encoding を統一
- **定期的なデータベース検証**: 保存されているデータ自体が破損していないか確認

```ruby
# config/initializers/response_encoding.rb
module ResponseEncodingMiddleware
  def self.included(base)
    base.after_action :ensure_response_encoding
  end
  
  private
  
  def ensure_response_encoding
    if response.media_type&.include?('json')
      response.body = response.body.force_encoding('UTF-8').encode('UTF-8', invalid: :replace, undef: :replace)
    end
  end
end
```

## 設計判断のポイント

国際化対応を進める際は、以下を事前に決めておくことが重要です。

1. **アプリケーション全体の標準 encoding を UTF-8 に統一する** – これが最も実用的です
2. **データベースの接続設定で encoding を明示する** – サーバー側のデフォルト設定に依存しない
3. **外部データソースからの入力を即座に統一する** – キャッシュ層や API 層で処理
4. **JSON レスポンスの生成直前に再度確認する** – 複数の処理を経た後の最終チェック

小規模なチームでも、この4つを実装することで、大半の encoding 関連の問題は回避できます。
