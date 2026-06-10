---
layout: post
title: "Rubyのブロック内で外側の変数を書き換えるとき、yieldの複数呼び出しで値が予期せず上書きされる理由"
date: 2026-06-10
categories: tech-verification
tags: ["Ruby", "クロージャ", "ブロック", "yield", "スコープ管理"]
author: OpenWorks
---

## 現場で起きやすい問題

複数の処理を並列・順序実行するコードを書いていて、ブロック内で外側の変数を更新するパターンがあります。単発の呼び出しではうまくいくのに、同じブロックを何度も実行する場面で予期しない値が残ってしまう──そういう経験は多くのRubyエンジニアにあるはずです。

特に、イベント処理や複数の非同期タスク、データ変換パイプラインを書くときに、この落とし穴に引っかかります。「ブロックって便利だな」と思って使い始めると、スコープの扱いで足をすくわれることがあるのです。

## 検証の目的と前提

このテーマを検証する目的は、以下の3点です。

- Rubyのブロック（`yield`）がクロージャとして外側の変数にアクセスする仕組みを明確にする
- 複数回の呼び出しで変数が汚染される具体的なシナリオを再現する
- 実務コードではどう設計判断すべきかを整理する

前提として、Ruby 2.7以降での動作を想定します。また、ブロックの基本構文は既に理解している読者を対象にしています。

## ブロックはクロージャ──外側のスコープを保持したまま実行される

Rubyのブロックは、定義されたときのスコープを「閉じ込める」クロージャです。つまり、ブロック内のコードは、ブロック外の変数に直接アクセスし、さらに**それを書き換えることもできます**。

これが便利な一方、複数の処理が同じ変数を更新するときに問題が起きます。

```ruby
result = []
counter = 0

def process_items(items)
  items.each do |item|
    yield item
  end
end

process_items(['a', 'b', 'c']) do |item|
  counter += 1
  result << "#{item}-#{counter}"
end

puts result.inspect
# => ["a-1", "b-2", "c-3"]
puts counter
# => 3
```

ここまでは期待通りです。ブロックが3回実行され、`counter`は3になります。

## 複数の異なるブロック呼び出しで変数が上書きされる

問題は、同じ変数を複数の独立したブロック呼び出しで更新するときに顕在化します。

```ruby
result = nil

def fetch_data(key)
  yield key
end

fetch_data('user_id') do |key|
  result = "User: 123"
end

puts result
# => "User: 123"

fetch_data('product_id') do |key|
  result = "Product: 456"
end

puts result
# => "Product: 456"
```

ここまでは当たり前です。しかし、以下のようなパターンではどうでしょう。

```ruby
handlers = []

def register_handler(&block)
  handlers << block
end

state = "initial"

register_handler do
  state = "handler_1"
end

register_handler do
  state = "handler_2"
end

# 後から順に実行
handlers[0].call
puts state
# => "handler_1"

handlers[1].call
puts state
# => "handler_2"
```

ここでも問題ありません。ですが、複数のハンドラが**同じ変数を同じ方法で更新しようとする設計**に陥ると、どうなるでしょう。

```ruby
accumulated = 0

def process_with_accumulator(values)
  values.each do |v|
    yield v
  end
end

# 複数回、同じ外側変数を更新するブロックを定義
process_with_accumulator([1, 2]) do |v|
  accumulated += v
end

puts accumulated
# => 3

process_with_accumulator([10, 20]) do |v|
  accumulated += v
end

puts accumulated
# => 33  # 3 + 10 + 20
```

これは正しく動作しています。では、何が「汚染」なのか。

## 実務で起きやすい汚染シナリオ

問題は、**ブロック内で複数の変数を操作し、それらが独立した複数の処理ステップで再利用される場合**です。

```ruby
# 複数のステップを順に実行するパイプライン
def execute_pipeline(steps)
  context = {}
  
  steps.each do |step|
    yield context, step
  end
  
  context
end

# 外側で初期化した変数
temp_result = nil
final_output = []

steps = ['step_1', 'step_2', 'step_3']

execute_pipeline(steps) do |context, step|
  # ステップごとに temp_result を上書き
  temp_result = "Processing #{step}"
  
  # ただし、最終出力には別の値を格納しようとしている
  if step == 'step_2'
    final_output << temp_result
  end
end

puts final_output.inspect
# => ["Processing step_2"]

# 問題: temp_result は最後の値で残る
puts temp_result
# => "Processing step_3"

# 別の処理で temp_result を再利用しようとすると...
another_pipeline(steps) do |context, step|
  # temp_result が前回の値のまま残っていることに気づかない
  puts temp_result  # "Processing step_3" が残っている
end
```

ここが「汚染」です。ブロック実行後に外側の変数が**予期しない値のまま残る**ため、後続の処理で予期しない挙動が起きます。

## 原因の本質──クロージャは変数そのものを参照している

Rubyのブロックがなぜこうなるのかは、**ブロックが変数のコピーではなく、変数そのものへの参照を保持している**からです。

```ruby
def create_handlers
  handlers = []
  value = 0
  
  3.times do |i|
    handlers << Proc.new do
      value += 1
      puts "Handler #{i}: value is now #{value}"
    end
  end
  
  handlers
end

my_handlers = create_handlers
my_handlers[0].call  # => "Handler 0: value is now 1"
my_handlers[1].call  # => "Handler 1: value is now 2"
my_handlers[2].call  # => "Handler 2: value is now 3"
```

3つのハンドラはすべて**同じ`value`変数**を参照しています。だから、どのハンドラを実行しても、同じ変数が更新されます。

## 設計判断──外側の変数を書き換えない設計へ

実務では、以下の判断が有効です。

**1. ブロック内で新しい変数を作り、戻り値として返す**

```ruby
result = []

def process_items(items)
  items.each do |item|
    yield item
  end
end

process_items(['a', 'b', 'c']) do |item|
  # 外側の変数を直接書き換えない
  processed = "item: #{item}"
  result << processed
end
```

**2. ブロックの戻り値を明示的に受け取る**

```ruby
def transform_with_block(items)
  items.map do |item|
    yield item
  end
end

result = transform_with_block(['a', 'b', 'c']) do |item|
  "item: #{item}"
end

puts result.inspect
```

**3. コンテキストオブジェクトを使い、メソッドの戻り値として返す**

```ruby
def execute_pipeline(steps)
  context = {}
  
  steps.each do |step|
    yield context, step
  end
  
  context  # 最後に context を返す
end

result = execute_pipeline(['step_1', 'step_2']) do |context, step|
  context[:last_step] = step
  context[:timestamp] = Time.now
end

puts result.inspect
```

## 実装上の注意点

複数のブロック呼び出しが同じ外側変数を参照する設計になっていないか、コードレビューで確認しましょう。特に以下のパターンは危険です。

- グローバル変数やインスタンス変数を、複数のブロック内で更新している
- ブロック外で初期化した変数を、複数のブロック呼び出しで順に上書きしている
- ブロック実行後に、その変数の値を次の処理で前提としている

テストを書くときは、**同じメソッドを複数回呼び出す**シナリオを含めることが重要です。単発の実行ではうまくいっても、繰り返し実行で問題が出るケースが多いからです。

## まとめ──クロージャの便利さと危険性のバランス

Rubyのブロックとクロージャは非常に強力で、コードを簡潔に書けます。ただし、その力は「外側のスコープに直接アクセスできる」ことにあり、その同じ性質が変数汚染を招きます。

実務では、ブロック内で外側の変数を書き換えない設計を心がけることで、予期しない副作用を防げます。戻り値を明示的に使う、コンテキストオブジェクトを返すといった手法は、保守性と可読性の両面で有効です。
