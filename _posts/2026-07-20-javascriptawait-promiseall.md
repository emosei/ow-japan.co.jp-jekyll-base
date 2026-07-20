---
layout: post
title: "JavaScriptの非同期処理で『await の順序』を変えるだけで、データベース往復が倍になる理由──Promise.all() の最適化と落とし穴を検証する"
date: 2026-07-20
categories: tech-verification
tags: ["JavaScript", "非同期処理", "Promise", "パフォーマンス最適化", "Node.js"]
author: OpenWorks
---

## 現場で起きる判断ミス

フロントエンドやNode.jsでデータベースアクセスを伴う非同期処理を書いていると、こんな場面に遭遇します。

「ユーザー情報を取得して、その後に注文履歴を取得する」という要件が来たとき、多くの開発者は素直にこう書きます。

```javascript
const user = await fetchUser(userId);
const orders = await fetchOrders(user.id);
```

この書き方は論理的には正しく見えます。ユーザー情報が必要だから先に取得する。その後で注文を取得する。しかし本当にそうでしょうか。

実は、この単純な順序の違いが、データベースへの往復回数を倍にしてしまう可能性があります。そして、その判断ミスは設計段階では気付きにくく、負荷テストの時点で初めて露呈することが多いのです。

## 検証の目的と前提条件

今回の検証は、以下の点を明確にすることを目的としています。

**目的:**
- `await` の順序と `Promise.all()` の使い分けが、実際のデータベース往復数にどう影響するか
- 依存関係がない非同期処理をどう見分け、どう最適化するか
- 実装の簡潔さと性能のバランスをどこで取るか

**前提条件:**
- Node.js環境（バージョン14以上）
- データベースクライアントライブラリ（例：pg、mysql2）
- レイテンシを測定できる環境
- 複数の非同期操作が並行できる設計

## パターン比較：順序依存 vs 並行実行

まず、実装パターンを3つ比較してみます。

### パターン1：素朴な順序実行（非効率）

```javascript
async function getUserWithOrders(userId) {
  const user = await fetchUser(userId);
  const orders = await fetchOrders(user.id);
  const payments = await fetchPayments(user.id);
  
  return { user, orders, payments };
}
```

このコードの問題点は、`fetchOrders` と `fetchPayments` が `user.id` に依存しているように見えますが、実は両者は互いに依存していないということです。それなのに順番に実行してしまうため、3回のデータベース往復が直列に実行されます。

ネットワークレイテンシが50msだとすると、総時間は約150msです。

### パターン2：依存関係を正しく認識した並行実行

```javascript
async function getUserWithOrders(userId) {
  const user = await fetchUser(userId);
  
  // user.id が必要な処理は並行実行
  const [orders, payments] = await Promise.all([
    fetchOrders(user.id),
    fetchPayments(user.id)
  ]);
  
  return { user, orders, payments };
}
```

ここでは `fetchUser` の結果を待ってから、`fetchOrders` と `fetchPayments` を並行実行します。総時間は約100msに短縮されます。

### パターン3：すべてが独立している場合

```javascript
async function getInitialData(userId) {
  const [user, config, notifications] = await Promise.all([
    fetchUser(userId),
    fetchSystemConfig(),
    fetchNotifications(userId)
  ]);
  
  return { user, config, notifications };
}
```

依存関係がなければ、すべて並行実行できます。総時間は約50msです。

## 実装での落とし穴

ここからが現場で実際に起こることです。

### 落とし穴1：依存関係の誤認識

開発者が「ユーザー情報を先に取得すべき」という心理的な順序で実装してしまい、実は依存していない処理を順番に書いてしまう場合があります。

```javascript
// ❌ 誤り：getOrderTotal は user.id を使うが、
// user の詳細情報には依存していない
const user = await fetchUser(userId);
const orderTotal = await fetchOrderTotal(user.id);
const userProfile = await fetchUserProfile(user.id);
```

`fetchOrderTotal` と `fetchUserProfile` は両方とも `user.id` さえあれば動作します。`user` オブジェクト全体を待つ必要はありません。

正しくは以下のようにすべきです。

```javascript
// ✅ 正しい：user.id だけが必要なら、
// user の取得と並行実行できる
const { id: userId } = await fetchUser(userId);
const [orderTotal, userProfile] = await Promise.all([
  fetchOrderTotal(userId),
  fetchUserProfile(userId)
]);
```

### 落とし穴2：Promise.all() 内での await の重複

```javascript
// ❌ 誤り：Promise.all() の中で await を使うと、
// 直列実行になってしまう
await Promise.all([
  (async () => {
    const user = await fetchUser(userId);
    return await fetchOrders(user.id);
  })(),
  // ...
]);
```

この書き方は見た目は並行実行に見えますが、クロージャの中で `await` が連鎖しているため、実質的には直列です。

### 落とし穴3：エラーハンドリングの複雑化

`Promise.all()` を使うと、1つのPromiseが失敗するとすべてが失敗します。部分的な失敗を許容したい場合は、`Promise.allSettled()` を使う必要があります。

```javascript
// 1つ失敗するとすべて失敗
const results = await Promise.all([
  fetchUser(userId),
  fetchOrders(userId)
]);

// 個別の失敗を許容
const results = await Promise.allSettled([
  fetchUser(userId),
  fetchOrders(userId)
]);

// 結果の確認
results.forEach((result, index) => {
  if (result.status === 'fulfilled') {
    console.log(`Task ${index}:`, result.value);
  } else {
    console.error(`Task ${index} failed:`, result.reason);
  }
});
```

## 実務での判断ポイント

### いつ最適化すべきか

性能最適化は必要ですが、すべての非同期処理を無理に並行化する必要はありません。

- **優先度が高い場合**：API応答時間が重要な場合、ユーザーが待つ画面の場合
- **優先度が低い場合**：バックグラウンド処理、管理画面、内部ツール

### 可読性とのバランス

複雑な依存関係を無理に `Promise.all()` で表現すると、コードが読みにくくなります。

```javascript
// 複雑な依存関係の場合、素朴な書き方の方が明確な場合もある
const user = await fetchUser(userId);
const profile = await fetchUserProfile(user.id);
const settings = await fetchSettings(profile.id);
```

この場合、各ステップが明確なので、順序を変えるメリットは限定的です。

### 本番運用での注意

データベース接続プールの制限を考慮する必要があります。並行実行を増やしすぎると、接続プールが枯渇し、逆にパフォーマンスが低下する可能性があります。

```javascript
// Node.js + PostgreSQL の例
const pool = new Pool({
  max: 20, // 接続プールサイズ
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 2000,
});

// 並行実行数がプールサイズを超えないよう注意
```

## 検証結果と実装のポイント

実際に計測してみると、以下のような結果が得られます（ネットワークレイテンシ50ms、3つの非同期処理の場合）。

| パターン | 実行時間 | DB往復数 |
|---------|--------|--------|
| 順序実行 | 約150ms | 3回 |
| 部分並行 | 約100ms | 3回（同時実行） |
| 完全並行 | 約50ms | 3回（同時実行） |

重要なのは、往復数は変わらないが、**同時実行の有無で実行時間が大きく変わる**ということです。

実装時の確認チェックリスト：

- [ ] 各非同期処理の依存関係を図に描いて確認したか
- [ ] 本当に前の処理の結果が必要か、IDだけで足りないか確認したか
- [ ] Promise.all() 内で await の連鎖がないか確認したか
- [ ] エラーハンドリング戦略を決めたか（all vs allSettled）
- [ ] 接続プールのサイズと並行実行数のバランスを確認したか
- [ ] 本番環境で負荷テストを実施したか

## 誰に向いているか、どんな案件で採用しやすいか

この最適化は、以下のような案件で効果が大きいです。

- **API レスポンス時間が重要な案件**：SPA、モバイルアプリのバックエンド
- **複数のマイクロサービスを呼び出す案件**：各サービスへのアクセスが並行できる
- **大量アクセスが予想される案件**：レイテンシの削減が全体スループットに影響

一方、以下のような案件では無理に最適化する必要はありません。

- **管理画面やバックオフィスツール**：ユーザー数が限定的
- **バッチ処理やスケジュール実行**：リアルタイム性が不要
- **複雑な依存関係がある場合**：可読性を優先する

現場では「理論的に最適」より「実装と保守が現実的」という判断が重要です。その上で、ボトルネックが明確になったら、段階的に最適化していくアプローチをお勧めします。
