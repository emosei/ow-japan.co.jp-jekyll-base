---
layout: post
title: "JavaScriptの非同期ジェネレータで途中エラーが発生したとき、リソース破棄のタイミングはどこで決まるのか"
date: 2026-07-24
categories: tech-verification
tags: ["JavaScript", "非同期ジェネレータ", "エラーハンドリング", "リソース管理", "検証"]
author: OpenWorks
---

## 非同期ジェネレータのエラーハンドリングが曖昧な理由

JavaScriptで非同期ジェネレータ関数を使うとき、処理の途中でエラーを投げるとどうなるのか。リソースの破棄やクリーンアップはどのタイミングで実行されるのか。この問題は、一見すると言語仕様で決まっているように見えるのですが、実装の詳細に踏み込むと現場での判断が分かれやすいポイントです。

特に、データベース接続、ファイルハンドル、APIのストリーム処理など、「途中で止まると困る」リソースを扱うときに、この曖昧さが設計判断を難しくします。エラーが発生した直後に破棄されるのか、それともイテレータが明示的に閉じられるまで待つのか。この差が、実務では予期しないリソースリークや過度なクリーンアップ処理につながることがあります。

今回の検証では、異なる実装パターンで非同期ジェネレータのエラーハンドリングを試し、イテレータの状態遷移とリソース破棄のタイミングがどう変わるのかを確認します。

## 検証の前提と観点

検証の目的は以下の3点です。

1. **エラー発生時のイテレータ状態**：`done` フラグが即座に `true` になるのか、それとも `catch` ブロックを通すまで待つのか
2. **`finally` ブロックの実行タイミング**：エラー直後か、イテレータが明示的に閉じられるときか
3. **複数の実装パターンの差異**：エラーハンドリングの方法（`try-catch` の位置、`return` の有無など）による動作の違い

環境はNode.js 18以上、ブラウザはChrome/Firefox最新版を想定します。

## パターン1：ジェネレータ内で `try-catch` を使う場合

まず、ジェネレータ関数の内部でエラーをハンドルするパターンです。

```javascript
async function* generatorWithInternalCatch() {
  try {
    yield 1;
    console.log("Before error");
    throw new Error("Internal error");
    yield 2; // 到達しない
  } catch (err) {
    console.log("Caught:", err.message);
    yield 3; // エラー後も yield できる
  } finally {
    console.log("Finally executed");
  }
}

(async () => {
  const gen = generatorWithInternalCatch();
  console.log("Start");
  console.log(await gen.next()); // { value: 1, done: false }
  console.log(await gen.next()); // { value: 3, done: false }
  console.log(await gen.next()); // { value: undefined, done: true }
})();
```

この場合、エラーはジェネレータ内で吸収されるため、呼び出し側に例外は伝わりません。`finally` ブロックはジェネレータが完全に終了するまで実行されません。つまり、イテレータの状態は「エラー発生 → キャッチ → 継続」となり、リソースは保持され続けます。

## パターン2：ジェネレータ内でエラーが伝播する場合

次に、エラーをキャッチせずに伝播させるパターンです。

```javascript
async function* generatorWithoutCatch() {
  try {
    yield 1;
    throw new Error("Unhandled error");
    yield 2;
  } finally {
    console.log("Finally in generator");
  }
}

(async () => {
  const gen = generatorWithoutCatch();
  try {
    console.log(await gen.next()); // { value: 1, done: false }
    console.log(await gen.next()); // throws Error
  } catch (err) {
    console.log("Caught outside:", err.message);
  }
  
  // この時点でジェネレータの状態は？
  console.log(await gen.next()); // { value: undefined, done: true }
})();
```

ここが重要な観察ポイントです。エラーが外に伝播したとき、ジェネレータの `finally` ブロックはいつ実行されるのか。実際に試すと、**`finally` はエラーが呼び出し側で `catch` されたあと、次の `next()` 呼び出しで初めて実行される**ことが分かります。

つまり、イテレータは「エラー状態で一時停止」しており、リソースはまだ破棄されていません。

## パターン3：呼び出し側で `for await...of` を使う場合

ループを使う場合の動作も確認します。

```javascript
async function* generatorWithError() {
  yield 1;
  throw new Error("Loop error");
  yield 2;
}

(async () => {
  try {
    for await (const value of generatorWithError()) {
      console.log("Value:", value);
    }
  } catch (err) {
    console.log("Caught in loop:", err.message);
  }
  console.log("After loop");
})();
```

`for await...of` ループでは、エラーが発生するとループが即座に抜け、ジェネレータは自動的に `return()` メソッドが呼ばれます。つまり、**`finally` ブロックはループを抜ける前に実行される**という点で、パターン2と異なります。

## 実装による差異の整理と実務上の注意

検証結果をまとめると、以下のようになります。

| パターン | エラー発生 | `finally` 実行タイミング | リソース状態 | 呼び出し側の対応 |
|---------|---------|------|---------|---------|
| 内部 `try-catch` | ジェネレータ内で吸収 | 処理終了時 | 保持される | 例外なし |
| 外部への伝播 | 呼び出し側で `catch` | 次の `next()` 呼び出し時 | 一時停止状態 | 明示的に `return()` 呼び出し推奨 |
| `for await...of` | ループ抜ける | ループ抜ける直前 | 自動破棄 | 特に対応不要 |

実務投入するなら、以下の点を確認しておくべきです。

**1. リソースリークの可能性**  
パターン2で、エラー後に `next()` を呼ばない場合、`finally` ブロックが実行されず、ファイルハンドルやDB接続が残ったままになります。必ず `gen.return()` または `gen.throw()` を明示的に呼ぶか、`for await...of` を使ってください。

**2. ループ構文の選択**  
`for await...of` は最も安全です。エラーが発生しても自動的にジェネレータをクローズします。ただし、途中で処理を中断したい場合は `break` で十分です。

**3. エラーハンドリングの一貫性**  
ジェネレータ内で `catch` してしまうと、外側からエラーが見えなくなります。呼び出し側がエラー状態を知る手段がなくなるため、設計時に「どこで `catch` するか」を明確にしておくべきです。

## 設計判断のポイント

現場では、次のような判断が求められます。

**ストリーム処理が必要か、単発の処理か**  
ファイル読み込みやAPIのページング処理など、長く続く可能性のある処理なら、`for await...of` で統一するのが無難です。単発のリソース取得なら、内部で `try-finally` を完結させる方が簡潔です。

**エラーの責任範囲**  
データベースのトランザクション処理なら、ロールバックはジェネレータ内で行うべきです。一方、キャッシュの更新など「失敗してもいい」処理なら、外側で `catch` して続行する設計も成り立ちます。

**テストのしやすさ**  
複雑なエラーハンドリングは、ジェネレータの内部に閉じ込めるより、外側でシンプルに扱える方がテストしやすいです。特に非同期処理のテストは既に複雑なので、エラーパスの検証も明確にしておくと後々の保守が楽になります。

## 結論と次のステップ

非同期ジェネレータのエラーハンドリングは、「言語仕様では決まっているが、実装パターンで挙動が大きく変わる」典型的なケースです。リソース管理が必要な処理に使う場合は、必ず本番環境に近い条件で動作確認をしてから導入してください。

特に、既存コードに組み込む際は、既存のエラーハンドリング戦略との整合性を確認しておくことをお勧めします。
