---
layout: post
title: "Rubyの正規表現がバックトラックで指数時間に化ける──ReDoS脆弱性が入力検証で静かに潜む理由と検証方法"
date: 2026-07-02
categories: tech-tips
tags: ["Ruby", "正規表現", "ReDoS", "入力検証", "パフォーマンス"]
author: OpenWorks
---

## 入力検証の正規表現が本番で突然遅くなる

Rubyで入力検証を書くとき、正規表現は便利です。メールアドレスやURLの形式チェック、ファイル名の許可文字確認など、パターンマッチングで一行で済みます。しかし現場では、ある特定の入力パターンを与えたとたんに、その検証処理が数秒、数十秒と固まってしまう現象に遭遇することがあります。

これが **ReDoS（Regular Expression Denial of Service）** です。悪意のある攻撃というより、正規表現の書き方の落とし穴が、ちょうど悪い入力パターンにぶつかるとき顕在化します。

開発環境では気づかず、本番で突然CPU使用率が跳ね上がる。ログを見ると、あるAPI呼び出しが異常に時間を食っている。原因を追うと、「ああ、この正規表現か」と気づく。そういう現場の判断を迫られる場面です。

## なぜバックトラックが指数時間に膨れ上がるのか

Rubyの正規表現エンジンは、マッチに失敗したとき、別の経路を試す **バックトラック** を行います。これ自体は正常な動作です。しかし、正規表現の書き方によっては、試すべき経路の数が入力の長さに対して指数関数的に増えることがあります。

典型的な例が、重複する量指定子（`+` や `*`）の組み合わせです：

```ruby
# 危険なパターン例
/^(a+)+b$/.match("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaac")
```

このパターンを見ると、`(a+)+` は「1文字以上のaが、1回以上繰り返される」という意味です。マッチ対象の文字列が `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaac`（aが28個、最後にc）だとします。

正規表現エンジンは以下のように動作します：

1. 最初、`(a+)+` が全てのaをマッチさせる
2. 次に `b` とマッチさせようとするが、文字は `c` なのでマッチ失敗
3. バックトラックして、`(a+)+` の最後の `a+` を1文字減らして再試行
4. また `b` とマッチ失敗、バックトラック
5. この繰り返しが、aの個数分だけ発生

aが28個なら、バックトラック試行は2の28乗に近い回数になります。30個なら約10億回。これが数秒から数十秒の遅延になるわけです。

## 現場で見落とされやすい理由

開発環境では、テストデータが「正常な形式」に限定されていることが多いです。メールアドレスなら `user@example.com`、URLなら `https://example.com/path` といった、短くて整形されたデータです。

だから、正規表現が危険でも、開発時には問題が浮かびません。本番では、ユーザーの入力やAPI経由のデータが予測不可能な形になり、たまたまバックトラックの最悪ケースにぶつかります。

また、正規表現の「見た目の複雑さ」と「実行時の危険性」は必ずしも一致しません。一見シンプルに見える正規表現でも、重複する量指定子が隠れていることがあります。

## 検証方法と対策

### 1. パターンの可視化と手動レビュー

まず、正規表現に重複する量指定子がないか確認します。危険なパターン：

```ruby
# 危険
/(a+)+/
/(a*)*b/
/(a|a)+/
/(a|ab)+/
```

安全な書き直し：

```ruby
# 安全（重複を避ける）
/a+/
/(a|b)+/
```

重複する量指定子を避けることが基本です。

### 2. Ruby標準の検証ツール

Rubyには、正規表現の危険性をチェックするgemがあります。`regexp_parser` と `regexp_examples` を組み合わせて、パターンの挙動を調べることができます：

```ruby
require 'regexp_parser'

pattern = /^(a+)+b$/
parsed = Regexp::Parser.parse(pattern)
puts parsed.inspect
# => 重複する量指定子を視覚的に確認
```

また、`timeout` を使って、マッチ処理に時間制限をかけることも有効です：

```ruby
require 'timeout'

pattern = /^(a+)+b$/
input = "a" * 30 + "c"

begin
  Timeout.timeout(1) do
    pattern.match(input)
  end
rescue Timeout::Error
  puts "正規表現がタイムアウト──ReDoS疑い"
end
```

開発時に、意図的に長い不正入力を与えてタイムアウトが発生しないか確認する習慣が重要です。

### 3. 入力制限とレイヤ分離

正規表現の前に、入力の長さを制限することも現実的な対策です：

```ruby
def validate_email(email)
  # 入力長を事前に制限
  return false if email.length > 254
  
  # その後で正規表現を適用
  /\A[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\z/.match?(email)
end
```

また、複雑な検証が必要な場合は、正規表現に頼らず、段階的なチェックに分割することも検討します：

```ruby
def validate_url(url)
  # 1. 長さチェック
  return false if url.length > 2048
  
  # 2. スキームチェック（正規表現は単純に）
  return false unless url.start_with?('http://', 'https://')
  
  # 3. URI.parse で構造チェック
  begin
    uri = URI.parse(url)
    uri.scheme && uri.host
  rescue URI::InvalidURIError
    false
  end
end
```

## 運用時の監視と対応

本番環境では、正規表現マッチの処理時間をログに記録することが有効です：

```ruby
def safe_regex_match(pattern, input, timeout_sec: 1)
  start = Time.now
  
  begin
    Timeout.timeout(timeout_sec) do
      result = pattern.match?(input)
      elapsed = Time.now - start
      
      # 処理時間が長い場合は警告
      if elapsed > 0.1
        Rails.logger.warn("Slow regex match: #{elapsed.round(3)}s")
      end
      
      result
    end
  rescue Timeout::Error
    Rails.logger.error("Regex timeout detected: #{pattern.inspect}")
    false
  end
end
```

アラートを設定して、正規表現マッチがタイムアウトする事象を監視することで、本番での問題を早期に検出できます。

## 小規模チームで始めるステップ

1. **既存の正規表現を棚卸し** ─ コード検索で `/.+/` や `/(.*)+/` などのパターンを探す
2. **危険パターンの洗い出し** ─ 重複する量指定子がないか確認
3. **テストケースの拡張** ─ 長い不正入力や境界値を意図的に試す
4. **タイムアウト機構の導入** ─ 既存の検証処理に `Timeout` を巻く
5. **監視ログの追加** ─ 本番での処理時間を記録

急いで全て変更する必要はありません。リスクの高い箇所（外部入力を直接受ける検証、ユーザー数が多いAPI）から段階的に対応することで、現実的な改善が進みます。

正規表現は強力なツールですが、入力が予測不可能な環境では、その落とし穴を意識した設計が必要です。
