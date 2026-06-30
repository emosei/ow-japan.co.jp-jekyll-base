---
layout: post
title: "eager loading では救えない──結合テーブルのカーディナリティが本番メモリを圧迫する理由と対策"
date: 2026-06-30
categories: it-trends
tags: ["ORM", "N+1問題", "メモリ最適化", "パフォーマンスチューニング", "本番運用"]
author: OpenWorks
---

## 開発環境では動くのに、本番でメモリ逼迫が起きる構図

ORM の N+1 問題に対して eager loading（先読み込み）で対策を打つことは、今では常識に近いアプローチです。Ruby on Rails なら `includes` や `preload`、Django なら `select_related` や `prefetch_related`、Java なら Hibernate の FetchType.EAGER。開発環境でテストデータを少量用意して動作確認すると「これで解決」と判断しがちですが、本番環境で急にメモリ使用率が高騰するケースが意外と多くあります。

その原因の多くが、**結合テーブルのカーディナリティ（濃度）が予想を大きく超えていた**という単純だが見落としやすい問題です。開発時に「ユーザーが持つ注文は平均 5 件程度」と想定していても、実際の本番データでは「特定のユーザーが数千件の注文を持つ」といった歪んだ分布が存在することは珍しくありません。eager loading はそうした外れ値に対して脆弱です。

## eager loading が内部でやっていることをもう一度確認する

eager loading の仕組みを簡潔に整理しておきます。

たとえば User と Order が 1 対多の関係にある場合、lazy loading（従来の遅延読み込み）では以下のように動きます：

```python
# lazy loading の場合
users = User.all()  # クエリ 1 回
for user in users:
    print(user.orders)  # ユーザーごとに N 回のクエリ
```

eager loading で対策すると：

```python
# eager loading の場合
users = User.prefetch_related('orders')  # 2 回のクエリで全データ取得
for user in users:
    print(user.orders)  # メモリ上のオブジェクトを参照
```

ここまでは理想的です。しかし内部では、User テーブルから 100 件取得した後、その 100 ユーザーに紐づく Order をすべてメモリに展開しています。1 ユーザーあたり Order が 10 件なら 1000 件のオブジェクト、100 件なら 10000 件のオブジェクトになります。

さらに問題は、**複数の関連テーブルを同時に eager loading する場合に顕著**になります。User が Order を持ち、Order が OrderItem を持つ場合：

```python
users = User.prefetch_related('orders', 'orders__items')
```

この 1 行は一見シンプルですが、メモリ上には User × Order × OrderItem の直積に近い数のオブジェクトが展開されます。User が 100 件、そのうち 1 ユーザーが 1000 件の Order を持ち、各 Order が平均 10 個の OrderItem を持つなら、メモリには 100 万個近いオブジェクトが積まれることになります。

## 本番データの分布が開発環境と異なる現実

開発時のテストデータは往々にして均等に分散しています。ユーザーごとの注文数も「平均 5 件」程度で設計されることが多いです。しかし本番環境では、以下のような偏りが必ず出ます：

- **ロングテール型**：大多数のユーザーは少数の注文を持つが、一部のヘビーユーザーが数千件を保有
- **季節変動**：特定期間に注文が集中し、時系列で見ると局所的にカーディナリティが跳ね上がる
- **レガシーデータの蓄積**：システムが古いほど、データベースには意図しない大量の関連レコードが眠っていることがある

こうした分布の歪みは、開発環境では再現しにくいです。意図的にテストデータを作ろうとしても「本当にそんなユーザーがいるのか」という疑問が先に立ち、テストケースから除外されがちです。

## 結合テーブルの行数爆発が起きるケース

eager loading で最も危険なのが、多対多の関係です。

ユーザーが複数のグループに属し、グループが複数のユーザーを持つ場合、結合テーブル（通常は `user_groups` など）の行数は「ユーザー数 × グループ数」の最悪ケースに達します。

```python
# 危険なパターン
users = User.prefetch_related('groups')
```

ユーザーが 1000 人、グループが 50 個、各ユーザーが平均 10 グループに属する場合、結合テーブルには 10000 行存在します。eager loading でこれをメモリに展開すると、オブジェクト数は 10000 個を超えます。さらに各グループが追加の属性（メタデータ、権限情報など）を持つなら、メモリ消費は加速度的に増えます。

実務では、こうした多対多の関係が複数層重なることもあります。User → Group → Permission → Role のような階層構造では、eager loading の連鎖が指数関数的にメモリを圧迫します。

## 現実的な対策：段階的なフィルタリングと限定読み込み

eager loading を完全に避けるのは難しいですが、以下のアプローチで危険性を大幅に軽減できます。

### 1. 結合テーブルに対して WHERE 条件を付ける

```python
# 全グループではなく、アクティブなグループだけを先読み込み
users = User.prefetch_related(
    Prefetch('groups', queryset=Group.objects.filter(is_active=True))
)
```

この工夫だけで、メモリ消費を数分の一に削減できることがあります。

### 2. ページネーションと組み合わせる

```python
# 一度に全ユーザーを取得するのではなく、100 件ずつ処理
page_size = 100
for offset in range(0, total_users, page_size):
    users = User.objects.all()[offset:offset+page_size].prefetch_related('orders')
    # 処理
```

ページネーションは API レスポンスだけでなく、バッチ処理やバックグラウンドジョブでも有効です。

### 3. 必要な列だけを取得する

```python
# 全カラムではなく必要なカラムだけ取得
users = User.objects.only('id', 'name').prefetch_related(
    Prefetch('orders', queryset=Order.objects.only('id', 'user_id', 'amount'))
)
```

ORM のオブジェクトサイズが小さければ、同じ行数でもメモリ消費は大幅に減ります。

### 4. 集計クエリで代替する

```python
# 個別の Order オブジェクトではなく、集計結果を取得
user_order_stats = User.objects.annotate(
    order_count=Count('orders'),
    total_amount=Sum('orders__amount')
).values('id', 'name', 'order_count', 'total_amount')
```

詳細データが不要なら、集計クエリの方が遥かに軽量です。

## 開発環境での検証をどう強化するか

本番で問題が顕在化するのを防ぐには、開発環境での検証を意識的に強化する必要があります。

- **テストデータの分布を本番に寄せる**：ダンプから一部のデータを復元するか、統計的に偏ったテストデータセットを作る
- **メモリプロファイラを定期的に走らせる**：Python なら `memory_profiler`、Ruby なら `derailed_benchmarks` など、ORM のメモリ消費を可視化するツールを使う
- **クエリログを監視する**：eager loading が実際に何個のオブジェクトを取得しているかを把握する

特に重要なのは「本番に近いデータ量での動作確認」です。開発環境でユーザーが 100 人なら、ステージング環境では意図的に 10000 人のダミーデータを投入してテストする習慣をつけると、こうした問題は早期に検出できます。

## 結論：eager loading は万能ではなく、設計判断が必要

eager loading は N+1 問題の強力な武器ですが、結合テーブルのカーディナリティが大きい場合には逆効果になります。導入する際は、単に「includes を付ける」のではなく、以下を確認してください：

- 実際に読み込まれるレコード数は何件か
- 1 ユーザーあたりの平均・最大カーディナリティは
- メモリに展開してもシステムリソースに余裕があるか

現場では「ORM の N+1 問題を避ける = eager loading を使う」という単純な図式で判断されることが多いですが、実務ではその先の「メモリとのトレードオフ」を常に意識する必要があります。時には lazy loading に戻す、時には SQL に寄せる、時には API 設計を見直す──そうした柔軟性が、安定した本番運用につながります。
