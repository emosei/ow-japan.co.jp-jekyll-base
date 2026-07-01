---
layout: post
title: "ActiveRecordの`includes`と`references`を同時に使うと、JOINとサブクエリが混在する理由と実装時の判断"
date: 2026-07-01
categories: tech-verification
tags: ["Ruby", "ActiveRecord", "Rails", "SQL最適化", "N+1問題"]
author: OpenWorks
---

## 現場で起きやすい問題

データベースへのクエリを最適化しようとして、ActiveRecordの`includes`と`references`を組み合わせたら、想定と違うSQLが生成されていた──こういった経験は多いのではないでしょうか。

特に関連テーブルの条件付きで絞り込みをしたいときに、`includes`で事前読み込みしつつ、`where`句で関連テーブルの条件を指定しようとすると、予想外のJOINとサブクエリが混在したSQLが実行されることがあります。実行計画が複雑になると、パフォーマンスが落ちるだけでなく、デバッグが難しくなります。

この記事では、その仕組みを検証し、設計時の判断基準を整理します。

## 検証の前提と目的

**目的：**
`includes`と`references`を組み合わせたときに、なぜJOINとサブクエリが混在するのか、その条件を明確にする

**前提条件：**
- Rails 6.x 以上（ActiveRecordの動作が安定している環境）
- SQLite、PostgreSQL、MySQLいずれでも動作確認可能だが、ここではPostgreSQLを主に対象
- N+1問題を回避することが目的

**比較観点：**
- `includes`のみの場合
- `includes` + `where`（関連テーブル条件なし）の場合
- `includes` + `references` + `where`（関連テーブル条件あり）の場合
- `joins` + `where`の場合

## 実装例と実際のSQL生成

まず、シンプルなモデル構成を想定します。

```ruby
class Post < ApplicationRecord
  has_many :comments
end

class Comment < ApplicationRecord
  belongs_to :post
end
```

### ケース1: `includes`のみ

```ruby
Post.includes(:comments).where(comments: { status: 'published' })
```

生成されるSQL（PostgreSQL）：

```sql
SELECT "posts".* FROM "posts"
WHERE "posts"."id" IN (
  SELECT "comments"."post_id" FROM "comments"
  WHERE "comments"."status" = 'published'
)

SELECT "comments".* FROM "comments"
WHERE "comments"."post_id" IN (...)
```

`includes`を指定していますが、`where`句で関連テーブルに条件をつけた途端に、**サブクエリが自動生成されます**。これはActiveRecordが「条件を満たす親レコードを先に絞り込む」という判断をしたためです。

### ケース2: `includes` + `references`

```ruby
Post.includes(:comments).references(:comments).where(comments: { status: 'published' })
```

生成されるSQL：

```sql
SELECT DISTINCT "posts".* FROM "posts"
LEFT OUTER JOIN "comments" ON "comments"."post_id" = "posts"."id"
WHERE "comments"."status" = 'published'

SELECT "comments".* FROM "comments"
WHERE "comments"."post_id" IN (...)
```

`references`を追加すると、**JOINに切り替わります**。しかし、その後の関連データ読み込みは相変わらずサブクエリ + WHERE IN になります。つまり、JOINとサブクエリが混在している状態です。

### ケース3: `joins`のみ

```ruby
Post.joins(:comments).where(comments: { status: 'published' }).distinct
```

生成されるSQL：

```sql
SELECT DISTINCT "posts".* FROM "posts"
INNER JOIN "comments" ON "comments"."post_id" = "posts"."id"
WHERE "comments"."status" = 'published'
```

この場合、単一のSQLで完結します。ただし、関連レコード（comments）は別途読み込む必要があります。

## 混在が起きる理由

ActiveRecordの設計では、`includes`は**N+1問題を回避するための事前読み込み戦略**です。

一方、`where`句で関連テーブルに条件をつけると、**親レコードを絞り込む必要**が生じます。ここで以下の判断が発生します。

1. **`references`がない場合**：「条件が関連テーブルにあるので、JOINせずにサブクエリで親を絞ろう」
2. **`references`がある場合**：「明示的にJOINするよう指示されたから、JOINで親を絞ろう」

しかし、どちらの場合でも、`includes`で指定した関連データの読み込みは**別の戦略**で実行されます。つまり、親の絞り込みと関連データの読み込みが異なるSQL戦略で動作するため、混在が起きるのです。

## 実務での判断基準

### 使い分けの指針

**`includes` + `references`を使う場面：**
- 親テーブルの条件で絞り込みが必要
- 関連テーブルの件数が少ない、または1対1の関連
- JOINの結果が重複しない（DISTINCT不要）

**`joins`を使う場面：**
- 親テーブルの条件で絞り込みが必要
- 関連テーブルの件数が多い可能性がある
- 関連データの全件読み込みが不要（集計や存在確認のみ）

**`includes`のみを使う場面：**
- 関連テーブルに条件がない
- 親テーブルの全件（または単純な条件のみ）を取得
- 関連データも全て必要

### 実装例：ベストプラクティス

```ruby
# ❌ 混在が起きやすい（避けるべき）
posts = Post.includes(:comments)
            .references(:comments)
            .where(comments: { status: 'published' })

# ✅ 明確な意図：親を絞り込んで、関連データも取得
posts = Post.joins(:comments)
            .where(comments: { status: 'published' })
            .distinct
            .includes(:comments)

# ✅ または、親の条件が明確なら
posts = Post.where(id: Comment.where(status: 'published').select(:post_id))
            .includes(:comments)
```

最後の例では、サブクエリを明示的に書くことで、実装者の意図が明確になり、保守性が向上します。

## 運用時に確認すべきポイント

実装後、以下を確認しましょう。

- **ログレベルをDEBUGに設定し、実際のSQLを確認する**
  ```ruby
  ActiveRecord::Base.logger = Logger.new(STDOUT)
  ```

- **本番環境でのクエリプランを測定する**
  ```sql
  EXPLAIN ANALYZE SELECT ...
  ```

- **大規模データでの動作確認**：テスト環境では問題なくても、本番でのレコード数で実行計画が変わることがあります

- **キャッシュの影響を排除する**：複数回実行して、キャッシュヒット率を観察する

## まとめ

`includes`と`references`の混在は、ActiveRecordが親の絞り込みと関連データの読み込みを異なる戦略で処理しているために起きます。

実務では、「何を絞り込みたいのか」「どのデータが必要か」を明確にしてから、`joins`か`includes`かを選ぶことが重要です。混在を避けることで、SQLが単純になり、パフォーマンスの予測可能性も向上します。
