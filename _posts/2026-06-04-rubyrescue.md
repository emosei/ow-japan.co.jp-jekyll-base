---
layout: post
title: "Rubyのrescueが広すぎると、本来検出すべき障害が無視されたまま運用される"
date: 2026-06-04
categories: tech-tips
tags: ["Ruby", "例外ハンドリング", "rescue", "エラー分類", "運用設計"]
author: OpenWorks
---

## 現場で起きている問題：例外を「まとめて握りつぶす」という判断

予約システムやAPI連携を扱うWebアプリケーションを長年見ていると、本番環境で起こる障害の大半は「既知のエラーハンドリングが広すぎて、予期しない例外が検出されなかった」という形で顕在化します。

具体的には、こういう場面です。

```ruby
def process_payment(order_id)
  begin
    payment_gateway.charge(order_id)
    order.update(status: 'paid')
  rescue => e
    logger.error("Payment failed: #{e.message}")
    false
  end
end
```

このコードは一見、エラーを適切に処理しているように見えます。でも実際には、何が起きているのでしょうか。

- データベース接続エラー
- 支払いゲートウェイのタイムアウト
- 金額計算の型不一致
- メモリ不足
- 権限不足

これらすべてが同じ `rescue` に吸収されます。その結果、本来は**即座に調査すべき障害**が、単なる「支払い失敗」として記録されたまま、数日後に監視アラートで初めて気づくということが起きます。

## なぜ「広いrescue」は現場で生まれるのか

エンジニアがこういう書き方をするのは、怠けているからではなく、**判断の難しさ**が背景にあります。

Rubyは動的型言語で、実行時に何が起こるか予測しにくい面があります。特にAPIやライブラリとの連携では、予期しない例外が飛んでくることがあります。その不安定性に対して「とりあえず全部catch」という防御的な書き方が出てきやすいのです。

また、システムが成長していく過程で、最初は「支払い処理の失敗」という単一の懸念で書かれたコードが、後から複数の責務を持つようになることもあります。その過程で、rescue の粒度が見直されないままになることも多いです。

## 問題の本質：「エラーの分類」を曖昧にしたままにする

重要なのは、**どの例外は回復可能で、どの例外は回復不可能か**を明確に分けることです。

運用の立場から見ると、エラーは大きく3つに分かれます。

1. **一時的で回復可能な障害**（ネットワークタイムアウト、一時的な外部API障害）
2. **ビジネスロジック上の失敗**（残高不足、無効な注文状態）
3. **システムレベルの障害**（データベース接続失敗、権限エラー、メモリ不足）

1番目は再試行やフォールバックで対応できます。2番目はユーザーに通知すればいい。でも3番目は、人間が介入して調査する必要があります。

それなのに、すべてを同じ `rescue` で処理すると、この分類が失われます。

## 実装の指針：例外を「種類ごと」に捕捉する

では、実際にどう書くべきか。基本的な考え方は、**具体的な例外を先に書き、その後で汎用的な例外を書く**ということです。

```ruby
def process_payment(order_id)
  begin
    payment_gateway.charge(order_id)
    order.update(status: 'paid')
  rescue PaymentGateway::TimeoutError => e
    # 一時的な障害。再試行ロジックに委ねる
    logger.warn("Payment timeout (will retry): #{e.message}")
    raise RetryableError, e.message
  rescue PaymentGateway::InsufficientFundsError => e
    # ビジネスロジック上の失敗。ユーザーに通知
    logger.info("Insufficient funds for order #{order_id}")
    false
  rescue ActiveRecord::Deadlock => e
    # データベースレベルの障害。再試行可能
    logger.warn("Database deadlock: #{e.message}")
    raise RetryableError, e.message
  rescue StandardError => e
    # 予期しない例外。アラートを上げて人間に知らせる
    logger.error("Unexpected error in payment: #{e.class} - #{e.message}")
    notify_error_monitoring(e)
    raise
  end
end
```

この書き方のポイントは：

- **具体的な例外を先に書く**：Rubyは上から順に評価するので、具体的なものが先に来る必要があります
- **回復可能な例外は明示的に再スロー**：単に `false` を返すのではなく、呼び出し元が判断できるように情報を渡す
- **予期しない例外は必ず上位に伝える**：`rescue StandardError` で全部握りつぶさない

## 運用段階で気づきやすくする工夫

実装だけでなく、運用でも工夫が必要です。

```ruby
# カスタム例外を定義して、分類を明確にする
class PaymentError < StandardError; end
class RetryablePaymentError < PaymentError; end
class NonRetryablePaymentError < PaymentError; end

# ログレベルを使い分ける
# - warn: 一時的な障害（自動リトライ対象）
# - error: システム障害（監視アラート対象）
# - info: ビジネスロジック上の失敗（通知不要）
```

さらに、監視・ロギングの設定で、`error` レベルのログが出たら即座に通知が来るようにする。これにより、予期しない例外が発生したときに、数時間単位で遅延することなく対応できます。

## 小規模チームで始めるなら

いきなり完璧な分類を目指す必要はありません。段階的に進めることをお勧めします。

1. **まず、外部API呼び出しの周辺から始める**：支払い、配送、認証など、外部との連携がある場所
2. **その次に、データベース操作**：トランザクション、デッドロック、接続エラーなど
3. **最後に、ビジネスロジック層**：バリデーション、状態遷移など

また、既存コードを急いで直す必要はありません。新しい機能や改修時に、意識的に細かいrescueを書く癖をつけることから始めるだけで、徐々に改善されます。

## 落とし穴：例外クラスの継承関係を理解しておく

Rubyの例外は継承階層を持っています。`StandardError` は `Exception` の子クラスですが、`SystemExit` や `Interrupt` は `StandardError` の親クラスです。

つまり、`rescue StandardError` と書いても、プロセス終了シグナル（`SystemExit`）やCtrl+C（`Interrupt`）は捕捉されません。これはむしろ安全な設計なのですが、うっかり `rescue Exception` と書くと、本来捕捉すべきではない例外まで握りつぶしてしまいます。

**ルール：`rescue Exception` は絶対に使わない。常に `rescue StandardError` か、より具体的な例外を指定する。**

## 運用を楽にするために

結局のところ、「広いrescueを避ける」というのは、**運用チームへの思いやり**でもあります。

エラーが起きたとき、オンコール対応者が「このエラーは重大なのか、それとも自動リトライで対応されるのか」を判断するのに、ログを読むだけで分かるようにしておく。これが、実は技術的な正確さよりも、実務では重要だったりします。
