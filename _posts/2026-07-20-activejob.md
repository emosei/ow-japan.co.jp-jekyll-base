---
layout: post
title: "ActiveJobの抽象化が隠す非同期処理の失敗──テスト環境で気づかない「再試行」と「タイムアウト」の実装ギャップ"
date: 2026-07-20
categories: tech-tips
tags: ["Ruby", "Rails", "ActiveJob", "非同期処理", "本番環境"]
author: OpenWorks
---

## 便利さの裏にある見えない落とし穴

Rails の ActiveJob は本当に便利です。キューイングバックエンド（Sidekiq、Resque、Delayed Job など）の実装詳細を隠してくれるので、開発者は `perform_later` と `perform` を書くだけで非同期処理が実現できます。

ですが、この抽象化の厚さが、本番環境でしか顕在化しない問題を生み出しやすいんです。

現場では、開発環境やテスト環境では「同期実行」で済ませてしまうことが多いですよね。`config.active_job.queue_adapter = :inline` で、ジョブが即座に実行されるように設定して、動作確認を終わらせてしまう。その時点では何の問題も見えません。

ところが本番環境に上がると、バックエンドが Sidekiq に切り替わり、ワーカープロセスが別プロセスで動き始める。そこで初めて「再試行の挙動が違う」「タイムアウトで失敗している」「デッドレターキューに溜まっている」といった問題が浮上するわけです。

## 見落とされやすい3つの実装ギャップ

### 1. 再試行ロジックの有無が環境で変わる

ActiveJob の `retry_on` や `discard_on` は、バックエンド依存の動作をします。

```ruby
class SendNotificationJob < ApplicationJob
  queue_as :default
  
  retry_on StandardError, wait: :exponentially_longer, attempts: 5
  discard_on ActiveJob::DeserializationError
  
  def perform(user_id)
    user = User.find(user_id)
    NotificationService.send(user)
  end
end
```

開発環境で `:inline` を使っていると、このコードは一度だけ実行されます。例外が発生したら、その場で再度発生するだけ。`retry_on` は何もしません。

本番の Sidekiq では、指数バックオフで 5 回まで再試行されます。つまり、開発環境では「ジョブが失敗する」という事実だけが見えて、本番では「失敗 → 待機 → 再試行 → 失敗 → ... 」というサイクルが始まるわけです。

データベース接続エラーやタイムアウトなら、再試行で解決することもあります。でも、ロジックエラーなら何度やっても失敗します。その間、ジョブはキューに残り続け、やがてデッドレターキューに送られます。

### 2. タイムアウト設定がバックエンドの仕様に隠される

ActiveJob では `:wait_until` や `:wait` で遅延実行を指定できますが、ジョブ自体の実行時間上限（timeout）は、バックエンドに委ねられています。

```ruby
class ProcessLargeFileJob < ApplicationJob
  queue_as :default
  
  def perform(file_id)
    file = StoredFile.find(file_id)
    # ファイル処理に最大 30 秒かかる想定
    process_file_with_timeout(file, timeout: 30)
  end
  
  private
  
  def process_file_with_timeout(file, timeout:)
    # タイムアウト処理をここで実装...
  end
end
```

開発環境で `:inline` なら、このジョブは同期実行されるので、タイムアウトは発生しません（Ruby のプロセスが生きている限り）。

本番の Sidekiq では、ワーカーの設定で `timeout` が決まっています。デフォルトは 25 秒。ジョブが 25 秒を超えると、ワーカープロセスが強制終了されます。ファイル処理が 30 秒かかるなら、本番では必ず失敗します。開発環境では成功していたのに。

### 3. 例外の種類と扱いが環境で異なる

ActiveJob は例外をキャッチして、バックエンドに「再試行すべきか、破棄すべきか」を判定させます。

```ruby
class FetchExternalDataJob < ApplicationJob
  queue_as :default
  
  retry_on Timeout::Error, wait: 10, attempts: 3
  discard_on StandardError
  
  def perform(resource_id)
    resource = Resource.find(resource_id)
    data = ExternalAPI.fetch(resource_id)  # タイムアウトの可能性
    resource.update(data: data)
  end
end
```

開発環境で `:inline` なら、`ExternalAPI.fetch` がタイムアウトしたとき、`Timeout::Error` がそのまま呼び出し元に伝播します。テストコードでも同じです。

本番の Sidekiq では、`Timeout::Error` は `retry_on` にマッチして再試行されます。でも、予期しない例外（例えば API がレスポンスを返さず接続がハング）は `StandardError` にマッチして破棄されます。

テスト環境で「例外が発生した」という事実だけを検証していると、本番で「なぜか一部のジョブが無音で消えている」という状況に陥ります。

## 実装時の現実的な判断ポイント

### テスト環境でもバックエンドを動かす

最も確実な対策は、テスト環境（少なくとも統合テスト）で実際のキューイングバックエンドを使うことです。

```ruby
# config/environments/test.rb
config.active_job.queue_adapter = :sidekiq  # または :test ではなく実バックエンド
```

ただし、単体テストまで実バックエンドにするとテスト速度が落ちるので、現実的には以下の分け方が多いです：

- **単体テスト**：`:test` アダプタ（同期実行、ジョブが enqueued されたことを検証）
- **統合テスト**：実バックエンド（Sidekiq など）を Docker で起動して、ジョブの実行、再試行、タイムアウトを検証

### ジョブごとに timeout と retry を明示的に設定する

```ruby
class TimeoutSensitiveJob < ApplicationJob
  queue_as :default
  sidekiq_options timeout: 60  # Sidekiq 用の明示的な設定
  
  retry_on Timeout::Error, wait: 5, attempts: 2
  discard_on StandardError  # 予期しない例外は破棄
  
  def perform(id)
    # 最大 60 秒で完了する処理を書く
  end
end
```

バックエンドが Sidekiq の場合、`sidekiq_options timeout: 60` で明示的に 60 秒を指定します。これがないと、Sidekiq のデフォルト（25 秒）が適用されます。

### 本番環境での監視を最初から組み込む

再試行やタイムアウトは、本番環境でのみ発生する現象です。だから、本番環境でのジョブ実行状況を可視化することが不可欠です。

```ruby
class MonitoredJob < ApplicationJob
  queue_as :default
  
  around_perform do |job, block|
    start_time = Time.current
    begin
      block.call
      Rails.logger.info("Job completed: #{job.class.name} in #{Time.current - start_time}s")
    rescue => e
      Rails.logger.error("Job failed: #{job.class.name}, error: #{e.class}, message: #{e.message}")
      raise  # 再試行ロジックに委ねる
    end
  end
  
  def perform(id)
    # ジョブ処理
  end
end
```

さらに、Sidekiq の Web UI や外部の監視ツール（DataDog、New Relic など）で、失敗率、再試行回数、デッドレターキューの溜まり具合を監視することが重要です。

## 小規模チームでの現実的な導入ステップ

1. **まずは開発環境で `:test` アダプタのまま進める**  
   単体テストの速度が大事な初期段階では、同期実行で十分です。

2. **本番環境が見えたら、統合テストに実バックエンドを追加する**  
   Docker Compose で Sidekiq を起動し、重要なジョブの再試行やタイムアウトをテストします。

3. **本番環境にジョブを上げる前に、timeout と retry の設定を明示的に書く**  
   「デフォルトに任せる」という判断は避けます。

4. **本番環境での監視を設定する**  
   Sidekiq の Web UI を見る習慣をつけ、失敗しているジョブがあれば即座に気づく体制を整えます。

## 結論：抽象化を信頼しすぎない

ActiveJob の抽象化は本当に便利ですが、それが「詳細を隠している」という事実を忘れずに。テスト環境と本番環境の動作が異なることを前提に、設計段階から timeout や retry を明示的に指定し、本番環境での監視を組み込むことが、後々のトラブルを防ぐための最短経路です。
