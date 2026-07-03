---
layout: post
title: "Rubyのメモリ解放タイミングがGC.disableで制御できない理由──長時間バッチ処理でのメモリ枯渇と設計判断"
date: 2026-07-03
categories: tech-tips
tags: ["Ruby", "ガベージコレクション", "バッチ処理", "メモリ管理", "パフォーマンス最適化"]
author: OpenWorks
---

## 問題が顕在化する現場の状況

Rubyで長時間走るバッチ処理を書いていると、ある時点からメモリ使用量が右肩上がりになり、最終的にプロセスがOOMで強制終了される。そこで「GC.disableで明示的にガベージコレクションを制御すれば、メモリを効率よく使えるのでは」と考えて試してみても、思ったように改善しない──というケースに遭遇することがあります。

実は、この問題の根本はGCの制御方法ではなく、**何がメモリを保持し続けているか**という設計レベルの課題にあります。GC.disableは確かに存在しますが、それは「不要なオブジェクトを明確に破棄する」という前提があってはじめて効果を発揮します。前提がなければ、GCを無効化することは単に問題を先送りするだけになってしまいます。

## RubyのGCと「保持参照」の見えない関係

Rubyのガベージコレクションは、到達不可能なオブジェクトを自動で回収します。しかし「到達不可能」というのは、グローバル変数、インスタンス変数、クロージャのキャプチャ、キャッシュなど、コード上のどこかから参照されていないことを意味します。

長時間バッチの典型的な構造を見てみましょう。

```ruby
# 典型的なメモリリークパターン
class DataProcessor
  def initialize
    @cache = {}  # グローバルな参照保持
  end

  def process_batch(records)
    records.each do |record|
      result = expensive_operation(record)
      @cache[record.id] = result  # ここでメモリが増え続ける
    end
  end

  def expensive_operation(record)
    # 大きなオブジェクトを生成
    large_data = fetch_and_transform(record)
    large_data
  end
end

processor = DataProcessor.new
# 数百万件のレコードを処理
processor.process_batch(huge_record_list)
```

このコードでは、@cacheがプロセス生存期間中ずっとメモリを保持します。GC.disableを呼んでも、GC.enableに戻してもGCは実行されますが、@cacheの参照は生きているため、キャッシュされたオブジェクトは回収されません。

## GC.disableが「効果がない」のではなく「前提が満たされていない」

GC.disableが有効に機能するシーンは限定的です。以下のような条件が揃っているときです。

- **一時的な大量オブジェクト生成**：ループ内で毎回新しいオブジェクトが生まれ、ループを抜ければ参照が消える
- **GCのオーバーヘッド削減**：不要なGC実行を避けて、明示的なタイミングで一括実行したい
- **メモリが十分**：一時的に使用量が増えても、後で全て回収できる余裕がある

しかし長時間バッチでは、これらの前提が崩れやすいです。

```ruby
# GC.disableが有効に機能する例
GC.disable

10_000_000.times do |i|
  # 毎回新しい文字列を生成
  temp_string = "Process #{i}: #{Time.now}"
  # ループを抜ければ参照が消える
end

GC.enable
GC.start  # ここで一括回収
```

上のコードなら、GC.disableはメモリ効率を改善します。しかし、以下のようにループ外で参照が残っていると、GCを制御しても無意味です。

```ruby
results = []

GC.disable
10_000_000.times do |i|
  temp_string = "Process #{i}: #{Time.now}"
  results << temp_string  # 参照が残る
end
GC.enable
GC.start  # resultsが大きすぎてOOM
```

## 現場で起こる判断ミス

バッチ処理でメモリが枯渇すると、多くの場合「GCの設定を変える」という対症療法に走ります。

- `GC.disable`を入れてみる
- `RUBY_GC_HEAP_GROWTH_MAX_SLOTS`などの環境変数を調整する
- Rubyのバージョンを上げてみる

これらは全て無駄ではありませんが、根本的には「どのオブジェクトがメモリを占有し続けているのか」を特定することが先です。

現場では以下の順序で判断すべきです。

1. **メモリプロファイリング**：どのオブジェクトが何個、どれだけのメモリを使っているか測定する
2. **参照の可視化**：グローバル変数、インスタンス変数、クロージャのキャプチャを洗い出す
3. **設計の見直し**：不要な参照を削除、またはバッチを分割する
4. **GC設定の最適化**：その後で初めて、GCのチューニングを検討する

## 実装上の対策パターン

### パターン1：キャッシュサイズの明示的制限

```ruby
class DataProcessor
  def initialize(max_cache_size: 1000)
    @cache = {}
    @max_cache_size = max_cache_size
  end

  def process_batch(records)
    records.each do |record|
      result = expensive_operation(record)
      @cache[record.id] = result
      
      # キャッシュサイズを制限
      if @cache.size > @max_cache_size
        # 最も古いエントリを削除
        oldest_key = @cache.keys.first
        @cache.delete(oldest_key)
      end
    end
  end
end
```

### パターン2：バッチ分割による参照の明示的破棄

```ruby
def process_large_dataset(file_path, batch_size: 10000)
  File.foreach(file_path) do |line|
    # 小分けにして処理
    process_batch_chunk(line, batch_size)
  end
end

def process_batch_chunk(data, batch_size)
  chunk = []
  data.each do |record|
    chunk << transform(record)
    
    if chunk.size >= batch_size
      save_to_db(chunk)
      chunk = []  # 明示的に参照を破棄
      GC.start if should_gc?  # 必要に応じてGC実行
    end
  end
  
  save_to_db(chunk) if chunk.any?
end
```

### パターン3：オブジェクトプール化による再利用

```ruby
class ObjectPool
  def initialize(object_class, initial_size: 100)
    @available = Array.new(initial_size) { object_class.new }
    @in_use = Set.new
  end

  def acquire
    obj = @available.pop || @available.first.class.new
    @in_use.add(obj)
    obj
  end

  def release(obj)
    obj.reset  # 状態をリセット
    @in_use.delete(obj)
    @available.push(obj)
  end
end

# 使用例
pool = ObjectPool.new(DataBuffer, initial_size: 50)

records.each do |record|
  buffer = pool.acquire
  buffer.load(record)
  process(buffer)
  pool.release(buffer)
end
```

## GC設定を触るなら、この3つを理解してから

やむを得ずGC設定を変更する場合は、以下の3つを把握した上で行ってください。

- **RUBY_GC_HEAP_GROWTH_MAX_SLOTS**：ヒープが一度に成長する最大サイズ。大きくするとGC頻度が減りますが、メモリ使用量が増えます
- **RUBY_GC_HEAP_OLDOBJECT_LIMIT_FACTOR**：新世代から老世代への昇格ルール。調整すると若いオブジェクトの回収頻度が変わります
- **GC.stat**：実際のGC動作を監視するコマンド。設定変更の効果を測定するときに使用します

```ruby
# GC統計の確認例
GC.stat.each { |k, v| puts "#{k}: #{v}" }

# 処理前後でのメモリ差分を測定
before = ObjectSpace.count_objects[:TOTAL]
process_batch
after = ObjectSpace.count_objects[:TOTAL]
puts "Created objects: #{after - before}"
```

## 小規模チームでの現実的な対応

リソースが限られた環境では、以下の優先順位で対応してください。

1. **バッチ分割**：最も効果的で、設計変更も小さい
2. **参照の明示的破棄**：変数のスコープを狭める、ブロック終了時にnilを代入する
3. **キャッシュサイズ制限**：LRUキャッシュライブラリを導入するのも手
4. **GC設定変更**：計測とテストが十分にできるなら、最後の手段として

GC.disableは「銀の弾」ではなく、設計が堅牢な上での最適化手段です。それを忘れずに。
