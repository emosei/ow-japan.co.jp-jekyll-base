---
layout: post
title: "関数型言語でOption/Either型に統一すると、呼び出し元の『どれを選ぶか』の判断が曖昧になる理由"
date: 2026-07-07
categories: tech-verification
tags: ["関数型言語", "エラーハンドリング", "型設計", "Option型", "Either型"]
author: OpenWorks
---

## 現場で起きる判断の停滞

関数型言語を導入した案件で、こういう場面に遭遇することがあります。

エラーハンドリングを `Option` 型と `Either` 型に統一した設計があって、ライブラリ側は「失敗する可能性がある」ことを型で表現している。呼び出し元も当然、パターンマッチで結果を処理する。ここまでは理屈通りです。

ところが運用が進むと、「この関数が返すのは `Option` なのか `Either` なのか、どっちで扱うべき？」という質問が頻繁に上がるようになります。型安全性があるはずなのに、なぜか判断が曖昧なままになってしまう。

その理由は、**統一されたエラー型が『何が起きたか』を隠すから**です。

## 型の統一と情報の喪失

具体的に考えてみましょう。以下は Elm 的な書き方ですが、Haskell や Scala でも同じ論理が当てはまります。

```elm
-- 統一されたパターン
type Result error value
  = Ok value
  | Err error

-- 複数の関数が同じ型を返す
validateEmail : String -> Result String String
validateEmail email =
  if String.contains "@" email then
    Ok email
  else
    Err "Invalid email format"

fetchUserFromDB : String -> Result String User
fetchUserFromDB userId =
  -- ネットワーク遅延、DB接続失敗、ユーザー未検出...
  -- すべてを Err String で返す
  Err "Database connection failed"

processUserData : String -> Result String ProcessedData
processUserData userId =
  case fetchUserFromDB userId of
    Ok user ->
      case validateEmail user.email of
        Ok email -> Ok (processData email)
        Err reason -> Err reason
    Err reason -> Err reason
```

ここで呼び出し元のコードを見ると、`Err` が返ってきたとき、開発者は次のような判断を迫られます：

- これは入力値の検証失敗か？（ユーザー側の問題で、再入力を促すべき）
- それとも外部サービスの一時的な障害か？（リトライすべき）
- あるいはデータ不整合か？（管理者に通知すべき）

ですが、型からは「`String` のエラーメッセージが返ってきた」という情報しかありません。

## 判断が曖昧になる仕組み

統一されたエラー型では、次のような問題が生じやすいです。

**1. エラーの分類が型に反映されない**

```elm
-- これだけでは、呼び出し元は区別できない
case result of
  Err msg -> 
    -- "Invalid email format" なのか
    -- "Database connection failed" なのか
    -- 文字列を解析しない限り判断できない
    handleError msg
  Ok value -> ...
```

**2. 関数ごとに『失敗の種類』が違うのに、型は同じ**

`validateEmail` の失敗は「入力が悪い」で、`fetchUserFromDB` の失敗は「外部依存が悪い」なのに、両方 `Result String _` です。

呼び出し元は、エラーメッセージの内容を見て「あ、これはこういう失敗なんだ」と推測するしかなくなります。

**3. 運用中にエラーメッセージが変わると、呼び出し元の判断が狂う**

ライブラリ側で「`"Database connection failed"` を `"DB: connection timeout"` に変更した」というような変更があると、呼び出し元の文字列マッチングが壊れます。

## Option型と Either型の選び分けの曖昧さ

さらに複雑なのは、**Option 型と Either 型の使い分け**です。

```haskell
-- Option: 値があるか、ないか（理由は関心がない）
lookup :: Eq a => a -> [(a, b)] -> Maybe b

-- Either: 値があるか、エラー理由は何か
validateAge :: Int -> Either String Int
validateAge age
  | age < 0 = Left "Age cannot be negative"
  | age > 150 = Left "Age seems unrealistic"
  | otherwise = Right age
```

これは理屈としてはクリアです。ですが、実装が進むにつれて：

- 「このデータベースクエリは `Maybe User` で返すべき？それとも `Either String User`？」
- 「ユーザーが見つからないのはエラーなのか、単に『値がない』状態なのか？」

こういう判断が、関数ごと、モジュールごとに分かれてしまいます。

## 実務で起きる設計の揺らぎ

現場では、こういう光景が見られます。

```haskell
-- モジュールA: Maybe で統一している
getUserName :: UserId -> Maybe String

-- モジュールB: Either で統一している
fetchUserProfile :: UserId -> Either UserError UserProfile

-- メインのビジネスロジック: 両方を扱わなければならない
processUser :: UserId -> Either AppError Result
processUser uid = do
  -- Maybe を Either に変換する
  name <- maybeToEither "User not found" (getUserName uid)
  profile <- fetchUserProfile uid
  -- ...
```

変換コード（`maybeToEither` など）が増えて、「なぜこの変換が必要なのか」という理由が曖昧なまま蓄積していきます。

## 判断を明確にする実装の工夫

では、どうするか。いくつかの手法があります。

**1. エラーの型を細分化する**

```haskell
data ValidationError
  = InvalidEmailFormat String
  | InvalidAgeRange Int
  deriving (Show, Eq)

data DatabaseError
  = ConnectionFailed String
  | QueryTimeout
  | RecordNotFound
  deriving (Show, Eq)

data AppError
  = Validation ValidationError
  | Database DatabaseError
  deriving (Show, Eq)

validateEmail :: String -> Either ValidationError String
fetchUser :: UserId -> Either DatabaseError User
```

こうすると、呼び出し元は型で「どんな失敗が起きうるのか」が明確になります。

**2. 関数のシグネチャに意図を明記する**

```haskell
-- Maybe を選ぶ場合は、『値がない』が正常系の一部であることを明示
findOptionalConfig :: Key -> Maybe Value

-- Either を選ぶ場合は、『エラーが発生した』と『値がない』を区別
loadRequiredConfig :: Key -> Either ConfigError Value
```

**3. ドメイン層とエラーハンドリング層を分ける**

```haskell
-- ドメイン層: ビジネス概念で失敗を表現
data DomainError
  = UserNotEligible String
  | InsufficientFunds Decimal
  deriving (Show)

-- HTTP層: ドメインエラーを HTTP ステータスに変換
handleDomainError :: DomainError -> (Int, String)
handleDomainError (UserNotEligible reason) = (400, reason)
handleDomainError (InsufficientFunds amount) = (402, "Insufficient funds")
```

## 実務投入前に確認すべきポイント

関数型言語の導入を検討しているなら、以下を事前に決めておくことをお勧めします。

- **エラー型の階層設計**: 全社で統一するのか、モジュール単位で異なるのか
- **Option と Either の使い分けルール**: どんな判断基準で選ぶのか、ドキュメント化する
- **エラーメッセージの管理**: 文字列マッチングに頼らない仕組み
- **チーム内での学習コスト**: 関数型パラダイムに不慣れなメンバーへの支援体制

実装が始まってから「統一されたはずなのに判断が曖昧」という状態に陥るのは、設計段階で『失敗とは何か』を言語化していないからです。

## まとめ

関数型言語の型安全性は強力です。ですが、**エラーハンドリングの型を統一すること自体が目的になると、かえって判断が曖昧になります**。

大切なのは、「この関数の失敗は何か」を型で表現し、呼び出し元が迷わずに対応できるようにすることです。統一性よりも、**明確性を優先する**ほうが、運用フェーズでの混乱を防げます。
