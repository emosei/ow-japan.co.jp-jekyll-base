---
layout: post
title: "Docker Composeで整える快適なローカル開発環境"
date: 2026-04-06
categories: tech-tips
tags: ["Docker", "Docker Compose", "開発環境", "ローカル開発", "インフラ整備"]
author: OpenWorks
---

# Docker Composeで整える快適なローカル開発環境

チーム開発を進める上で「ローカル環境の構築に時間がかかる」「メンバーごとに環境が異なってしまう」といった課題に直面した経験はないでしょうか。Docker Composeを活用すれば、こうした悩みを効率的に解決できます。本記事では、Docker Composeの基本から実践的な使い方までをご紹介します。

## Docker Composeとは

Docker Composeは、複数のコンテナを定義・管理するためのツールです。`docker-compose.yml`というYAML形式のファイルに、Webアプリケーション、データベース、キャッシュなど必要なサービスを記述することで、複数のコンテナを一括で起動・停止できます。

従来のDockerでは個別にコンテナを起動する必要がありましたが、Docker Composeを使うと「1つのコマンド」で開発環境全体を構築できるため、オンボーディング時間の短縮やチーム内での環境差異の解消につながります。

## 基本的な設定例で理解する

実際に、Node.js + PostgreSQLの組み合わせを例に見てみましょう。

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/myapp
    depends_on:
      - db
    volumes:
      - .:/app

  db:
    image: postgres:15
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
      POSTGRES_DB: myapp
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

このファイルがあれば、`docker-compose up`で両方のサービスが立ち上がります。ポイントとしては以下の通りです：

- **build**: Dockerfileからイメージをビルド
- **image**: Docker Hubから既存イメージを使用
- **ports**: コンテナのポートをホストマシンにマッピング
- **environment**: 環境変数を設定
- **depends_on**: サービス間の依存関係を指定
- **volumes**: ファイルシステムの永続化やマウント

## 開発効率を高めるテクニック

### ホットリロードの設定

`volumes`を活用することで、ローカルのコードを編集すると自動的にコンテナ内に反映されます。上記の例で`volumes: - .:/app`と指定することで、プロジェクトルート全体をコンテナ内にマウントしています。これにより、コンテナの再起動なしにコード変更を確認できます。

### マルチステージビルド

本番環境と開発環境で異なるDockerfileを使いたい場合、Composeファイルで`target`を指定することで対応できます。

```yaml
services:
  app:
    build:
      context: .
      target: development
```

### 環境別設定ファイルの活用

`docker-compose.override.yml`を作成することで、ローカル開発時のみの設定を追加できます。本来の`docker-compose.yml`は本番に近い設定を保ちながら、ローカル用のカスタマイズが可能です。

## よくあるトラブルと対策

**ポート競合エラー**: 既に別のプロセスがポート3000を使用している場合、`ports`セクションのマッピングを変更します（例：`"3001:3000"`）。

**ネットワーク接続の問題**: コンテナ間通信は自動的に設定されます。ホスト名には`localhost`ではなくサービス名（例：`db`）を使用してください。

**データベース初期化の遅延**: `depends_on`だけでは不十分な場合があります。健全性チェック機能を追加するか、起動スクリプトで接続確認を行いましょう。

## まとめ

Docker Composeは、ローカル開発環境の構築・管理を劇的に簡素化してくれるツールです。チーム全体で同じ環境を共有でき、オンボーディングも迅速化します。複雑な環境こそDocker Composeの価値が高まるため、まずは小さなプロジェクトから導入してノウハウを蓄積することをお勧めします。

効率的な開発ワークフロー実現の第一歩として、ぜひDocker Composeを活用してみてください。
