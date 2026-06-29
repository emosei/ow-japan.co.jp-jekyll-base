---
layout: post
title: "Webワーカーとメインスレッド間のstructured cloneが失敗する型が本番環境で初めて浮上する理由──開発環境との検証ギャップ"
date: 2026-06-29
categories: tech-verification
tags: ["JavaScript", "Webワーカー", "structured clone", "開発環境と本番環境", "型検証"]
author: OpenWorks
---

## 開発環境では「たまたま」うまくいく

JavaScriptでWebワーカーを使う案件で、メインスレッドとワーカー間でデータを受け渡す際、`postMessage()`経由でやり取りされるオブジェクトは自動的に**structured clone**によって複製されます。この仕組み自体は安定していますが、「どの型がclone可能か」という判定が、開発環境と本番環境で異なる結果になる現象が現場では珍しくありません。

開発環境では小規模なテストデータ、限定的なブラウザ環境、単純な構造のオブジェクトばかり扱うため、問題が顕在化しません。ところが本番環境に上げると、複数のブラウザ、多様なユーザー環境、複雑なオブジェクト構造が現れ、突然エラーが多発するという流れです。

この記事では、実際に何が起きているのか、どこで検証を落としやすいのか、そして実務投入前に確認すべきポイントを整理します。

## structured cloneが「失敗する」仕組み

### 型判定の曖昧さ

structured cloneは、JavaScriptの仕様で定められた特定の型のみを複製できます。対応している主な型は以下の通りです。

- プリミティブ型（number, string, boolean, null, undefined）
- Date, Map, Set, RegExp
- ArrayBuffer, TypedArray（Uint8Array等）
- Blob, File
- ImageData
- 通常のオブジェクト（plain object）とArray

一見すると「大抵のものはいけるんじゃないか」と思いがちです。しかし開発環境では以下のような状況が生まれやすいのです。

**開発環境での検証不足な例：**

```javascript
// メインスレッド
const userData = {
  id: 123,
  name: "User",
  createdAt: new Date(),
  metadata: {
    tags: ["tag1", "tag2"],
    config: {
      enabled: true
    }
  }
};

worker.postMessage({ data: userData });
```

このコードは開発環境では問題なく動きます。Date型も含まれていますが、structured cloneが対応しているからです。

ところが本番環境では、APIレスポンスやORM経由で取得したオブジェクトに、予期しない型が混在していることがあります。

### 本番環境で浮上する型の例

実務では以下のような「一見すると普通のオブジェクト」が問題になります。

**Symbolプロパティを含むオブジェクト**

```javascript
const obj = {
  id: 1,
  [Symbol.for('internal')]: 'value'
};

// structured cloneはSymbolを複製できない
worker.postMessage({ data: obj }); // エラー
```

**カスタムクラスのインスタンス**

```javascript
class User {
  constructor(name) {
    this.name = name;
  }
  
  greet() {
    return `Hello, ${this.name}`;
  }
}

const user = new User("Alice");
worker.postMessage({ data: user }); // エラー
```

User クラスのインスタンスは、プロトタイプチェーンを含む複雑な構造を持つため、structured cloneでは複製できません。開発環境でたまたまシンプルなオブジェクトしか扱わなければ、このエラーに気づかないのです。

**循環参照を含むオブジェクト**

```javascript
const obj = { name: "test" };
obj.self = obj; // 循環参照

worker.postMessage({ data: obj }); // エラー
```

開発環境では単純なテストデータを使うため、意図しない循環参照に気づかないまま本番に上げられることがあります。

## 開発環境と本番環境のギャップが生まれる理由

### 1. テストデータの単純性

開発環境では手書きのモックデータやシンプルなテストフィクスチャを使うことがほとんどです。一方、本番環境ではデータベース、API、サードパーティライブラリなど複数の層を経由したオブジェクトが流れてきます。

### 2. ブラウザの挙動差異

structured cloneの実装詳細は、ブラウザベンダーごとに微妙に異なります。開発環境でテストしたブラウザと、本番ユーザーが使うブラウザが異なると、同じコードでも結果が変わることがあります。

### 3. 型チェックの不在

JavaScriptは動的型言語のため、オブジェクトの構造を事前に検証する仕組みがありません。ワーカーに送信する直前に「このオブジェクトは本当にclone可能か」という確認が行われないまま本番に進むことが多いのです。

## 実務投入前の検証ポイント

### 検証1: 送信前のオブジェクト構造を明確にする

```javascript
// ワーカーに送信するデータの型定義（TypeScriptの例）
interface WorkerMessage {
  type: 'process';
  payload: {
    id: number;
    name: string;
    timestamp: Date;
    metadata?: Record<string, unknown>;
  };
}

// 送信側
function sendToWorker(data: WorkerMessage) {
  // 送信前にチェック
  if (!isCloneable(data)) {
    console.error('This object cannot be cloned');
    return;
  }
  worker.postMessage(data);
}
```

### 検証2: cloneable判定ヘルパーの実装

```javascript
function isCloneable(obj) {
  const cloneableTypes = [
    'undefined', 'boolean', 'number', 'string', 'bigint',
    'Date', 'RegExp', 'Map', 'Set', 'ArrayBuffer',
    'Uint8Array', 'Blob', 'File', 'ImageData'
  ];
  
  const type = Object.prototype.toString.call(obj).slice(8, -1);
  
  if (cloneableTypes.includes(type)) {
    return true;
  }
  
  if (type === 'Object' || type === 'Array') {
    // 再帰的にチェック
    for (const key in obj) {
      if (typeof key === 'symbol') {
        return false; // SymbolプロパティがあればNG
      }
      if (!isCloneable(obj[key])) {
        return false;
      }
    }
    return true;
  }
  
  return false; // その他のカスタムクラス等はNG
}
```

### 検証3: 複数環境・複数ブラウザでの動作確認

開発環境での検証に加えて、以下を必ず確認してください。

- Chrome、Firefox、Safari、Edgeなど主要ブラウザ
- 本番環境と同じデータスキーマ（API仕様書から）
- 実際のAPIレスポンスを使ったエンドツーエンドテスト

### 検証4: エラーハンドリングの実装

```javascript
worker.onmessage = (event) => {
  try {
    const result = event.data;
    // 処理
  } catch (error) {
    if (error.name === 'DataCloneError') {
      console.error('Failed to clone data for worker:', error);
      // フォールバック処理
    }
  }
};

// ワーカー側でも同様に
self.onmessage = (event) => {
  try {
    const data = event.data;
    // 処理
    self.postMessage({ success: true, result });
  } catch (error) {
    self.postMessage({ success: false, error: error.message });
  }
};
```

## 実務で採用する際の判断基準

**Webワーカーの活用が有効な案件：**

- 重い計算処理（画像処理、データ集計、暗号化など）
- 大量のデータ変換（JSON解析、CSV処理）
- 長時間実行の処理（UIブロッキング回避）

**この場合の留意点：**

- ワーカーに送信するデータは「シリアライズ可能な形」に事前に整形する
- 複雑なドメインモデルをそのまま送らない
- 送受信時の変換ロジックを集約し、テストしやすくする

**小規模案件や型の複雑さが高い場合：**

- ワーカーの導入そのものを見直す
- UIブロッキングが本当に問題か、実際に測定する
- 必要ならWeb Workers APIの代替（setTimeout分割、requestIdleCallback等）を検討する

## まとめ

structured cloneの失敗は、開発環境では「偶然」見つかりにくく、本番環境で「突然」現れる典型的なギャップです。原因は検証の不足ではなく、開発環境と本番環境で流れるデータの複雑さが根本的に異なるからです。

実務投入前には、送信オブジェクトの型を明示的に定義し、複数環境で動作確認し、エラーハンドリングを整備することが重要です。小さな手間ですが、本番環境での急なトラブルを防ぐ効果は大きいです。
