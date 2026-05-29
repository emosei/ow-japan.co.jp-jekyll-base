---
layout: post
title: "Goのsync.WaitGroupが「完了待ち」で見落とす競合状態──並行処理検証の再現性と運用の落とし穴"
date: 2026-05-29
categories: tech-verification
tags: ["Go", "並行処理", "sync.WaitGroup", "競合状態", "テスト検証"]
author: OpenWorks
---

## 導入：「完了した」と「正しく完了した」の違い

Go の並行処理を扱う案件では、複数の goroutine の完了を待つために `sync.WaitGroup` がよく使われます。シンプルで信頼性が高いライブラリですが、実務では「すべての goroutine が終わった」という状態と「すべてのタスクが正しく完了した」という状態の間に、見えにくい落とし穴があります。

現場では、開発環境では問題なく動作するのに、本番で時々データの不整合や予期しない終了が起きるというケースに何度も遭遇してきました。その多くは、WaitGroup の `Done()` 呼び出しと実際の処理完了の間に、タイミング依存の競合状態が隠れていたのです。

この記事では、WaitGroup の仕組みを再検証し、どうして完全な同期が難しいのか、そして実務でどう向き合うべきかを整理します。

## WaitGroupの基本動作と「完了」の定義のズレ

WaitGroup は内部カウンタで goroutine の数を管理し、`Add()` で増やし、`Done()` で減らし、`Wait()` でカウンタがゼロになるまでブロックします。シンプルな仕組みですが、ここで重要なのは「Done() が呼ばれた = 処理が完全に終わった」ではないという点です。

```go
func worker(id int, wg *sync.WaitGroup, ch chan int) {
    defer wg.Done()  // ここでカウンタが減る
    
    // 実際の処理
    result := processData(id)
    ch <- result     // 送信完了を待たない可能性
}

func main() {
    var wg sync.WaitGroup
    ch := make(chan int, 0)  // バッファなし
    
    wg.Add(3)
    go worker(1, &wg, ch)
    go worker(2, &wg, ch)
    go worker(3, &wg, ch)
    
    wg.Wait()  // ここで戻る
    // しかしチャネルの受信側がまだ準備できていない可能性
    close(ch)  // パニックの可能性
}
```

上の例では、`wg.Wait()` が戻った時点では、3つの goroutine はすべて `Done()` を呼び終わっています。しかし、チャネルへの送信がまだ完了していない、あるいは受信側がまだデータを取り出していない状態かもしれません。WaitGroup は「カウンタがゼロになった」という機械的な条件でしか同期していないのです。

## 並行処理検証の再現性が低い理由

並行処理のバグは、実行のたびに異なる結果を生むことがあります。これは CPU のスケジューリング、OS の割り当て、メモリアクセスのタイミングに依存するためです。

WaitGroup を使ったコードの検証では、以下のような現象がよく起きます：

- **開発環境では再現しない**：マシンのリソースが十分で、goroutine が順序よく実行されるため、競合状態が顕在化しない
- **テスト環境では時々失敗**：負荷が高い環境では、スケジューリングのばらつきが大きくなり、稀に失敗する
- **本番で定期的に発生**：大量の goroutine が走る環境では、競合状態が頻繁に起きる

実務では、こうした再現性の低いバグを追うのに多くの時間を費やします。ログに記録されない瞬間的な不整合、タイムアウト、デッドロックなど、症状は多様です。

## 検証手法：race detector と負荷テストの組み合わせ

Go には `race` フラグが用意されており、競合状態を検出できます。ただし、これは**データ競合**（同じメモリ領域への同時アクセス）を検出するもので、論理的な競合状態（WaitGroup の使い方の誤りなど）は検出できません。

実務で有効な検証手法は以下の通りです：

### 1. Race detector の活用

```bash
go test -race ./...
```

これにより、メモリレベルの競合状態が検出されます。ただし、オーバーヘッドが大きいため、本番環境では使えません。

### 2. 負荷テストと統計的検証

```go
func TestConcurrentProcessing(t *testing.T) {
    for iteration := 0; iteration < 1000; iteration++ {
        var wg sync.WaitGroup
        results := make([]int, 0)
        mu := sync.Mutex{}
        
        for i := 0; i < 100; i++ {
            wg.Add(1)
            go func(id int) {
                defer wg.Done()
                // 処理
                mu.Lock()
                results = append(results, id)
                mu.Unlock()
            }(i)
        }
        
        wg.Wait()
        
        if len(results) != 100 {
            t.Fatalf("iteration %d: expected 100, got %d", iteration, len(results))
        }
    }
}
```

このテストを何度も実行し、ときどき失敗するかどうかを確認します。1000 回のイテレーションで一度も失敗しなければ、比較的安全と言えます。

### 3. コンテキストタイムアウトによる検証

```go
func TestWithContext(t *testing.T) {
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    
    var wg sync.WaitGroup
    done := make(chan struct{})
    
    wg.Add(10)
    for i := 0; i < 10; i++ {
        go func() {
            defer wg.Done()
            // 処理
            time.Sleep(100 * time.Millisecond)
        }()
    }
    
    go func() {
        wg.Wait()
        close(done)
    }()
    
    select {
    case <-done:
        // 正常完了
    case <-ctx.Done():
        t.Fatal("timeout: WaitGroup did not complete in time")
    }
}
```

タイムアウトを設定することで、デッドロックやハング状態を検出できます。

## WaitGroupの制限と設計上の対策

WaitGroup が「完全な同期」を保証できない理由は、その設計の単純さにあります。以下の制限を理解した上で、使い分けることが重要です。

| 観点 | WaitGroup の制限 | 対策 |
|------|-----------------|------|
| 完了の定義 | カウンタがゼロになったのみ | チャネルやミューテックスで追加同期 |
| エラーハンドリング | エラー情報を返さない | エラーチャネルを別途用意 |
| タイムアウト | 無制限に待つ | context.WithTimeout を組み合わせ |
| キャンセル | 途中で止められない | context.WithCancel で制御 |

実務では、単純な「すべて完了まで待つ」という場面ならば WaitGroup で十分です。しかし、エラーハンドリングやタイムアウト、キャンセルが必要な場面では、context パッケージやエラーグループパターン（例：`golang.org/x/sync/errgroup`）の使用を検討すべきです。

## 本番投入前の確認チェックリスト

WaitGroup を使ったコードを本番環境に投入する際は、以下の点を確認しておくと、後からのトラブルを減らせます：

- **race detector で検証済みか**：`go test -race` を実行し、メモリ競合がないことを確認
- **負荷テストで安定性を確認したか**：開発環境よりも高い並行数でテストを実施
- **タイムアウト処理は入っているか**：無限待機を防ぐため、context タイムアウトを組み合わせたか
- **エラーハンドリングは十分か**：goroutine 内でのエラーを適切に記録・報告できるか
- **ログ出力でデバッグ可能か**：本番で問題が起きたとき、goroutine の進捗状況を追跡できるか

実務では、テストが通ったからといって本番環境でも同じ動作をするとは限りません。特に並行処理は、環境依存性が高いため、段階的なロールアウトや監視を組み合わせることが大切です。

## まとめ：WaitGroup は「合図」であって「保証」ではない

WaitGroup は Goの並行処理を扱う上で非常に便利なツールですが、それが「すべての処理が完全に終わった」ことを保証するわけではないという点が、実務で見落とされやすいポイントです。

カウンタがゼロになったのは、あくまで「各 goroutine が Done() を呼んだ」という機械的な条件に過ぎません。その後の通信、ファイル書き込み、データベース確定などは、WaitGroup の管轄外です。

現場では、WaitGroup の動作を理解した上で、必要に応じて context、チャネル、ミューテックスを組み合わせ、検証段階では race detector と負荷テストで念入りに確認することが、安定した並行処理システムへの近道だと考えています。
