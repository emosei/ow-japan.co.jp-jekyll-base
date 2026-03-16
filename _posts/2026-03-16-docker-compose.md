---
layout: post
title: "Docker Composeで本番に近い開発環境を構築する"
date: 2026-03-16
categories: tech-verification
tags: ["Docker", "Docker Compose", "開発環境", "マイクロサービス", "コンテナ化"]
author: OpenWorks
---

# Docker Composeで本番に近い開発環境を構築する

開発環境と本番環境の差異により、「ローカルでは動いていたのに、本番で動かない」という悩みを抱えたことはありませんか？このような問題を軽減する方法として、Docker Composeを活用した本番に近い開発環境の構築をご紹介します。

## Docker Composeが必要な理由

近年のWebアプリケーション開発では、複数のマイクロサービスで構成されることが一般的です。アプリケーション、データベース、キャッシュレイヤーなど、複数のコンテナが連携して動作する環境を、ローカルマシンで簡単に再現できることは非常に重要です。

Docker Composeはこれらの複数のコンテナを一度に起動・管理できるツールで、本番環境により近い環境をローカルで実現できます。開発チーム全体で同じ環境を共有でき、「自分の環境では動く」という課題を解決します。

## 実践的なdocker-compose.ymlの構成例

まずは、Webアプリケーション開発における一般的な構成例を見てみましょう。

```yaml
version: '3.8'

services:
  web:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: myapp_web
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=development
      - DB_HOST=db
      - REDIS_URL=redis://cache:6379
    volumes:
      - .:/app
      - /app/node_modules
    depends_on:
      - db
      - cache
    networks:
      - appnetwork

  db:
    image: postgres:15-alpine
    container_name: myapp_db
    environment:
      POSTGRES_USER: appuser
      POSTGRES_PASSWORD: password
      POSTGRES_DB: appdb
    volumes:
      - db_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    networks:
      - appnetwork

  cache:
    image: redis:7-alpine
    container_name: myapp_cache
    ports:
      - "6379:6379"
    networks:
      - appnetwork

volumes:
  db_data:

networks:
  appnetwork:
    driver: bridge
```

このファイルでは、WebアプリケーションとPostgreSQL、Redisが連携する環境を定義しています。

## 本番環境に近づけるための工夫

### 環境変数の適切な管理

本番環境と開発環境で異なる設定は、`.env`ファイルで管理します。

```
DB_HOST=db
DB_USER=appuser
DB_PASSWORD=devpassword
LOG_LEVEL=debug
```

docker-composeでは`env_file`で読み込めます：

```yaml
services:
  web:
    env_file: .env
```

ただし、本番のシークレットキーを開発環境に含めないよう注意してください。

### ボリュームマウントの活用

開発時はソースコードをボリュームマウントして、コード変更を即座にコンテナに反映させます。一方、本番環境ではイメージの完成後にデプロイするため、この点が異なります。開発専用の`docker-compose.override.yml`を作成し、本体の`docker-compose.yml`と組み合わせる方法が効果的です。

### ネットワーク構成の統一

Docker Composeで定義したネットワーク（上記の`appnetwork`）により、サービス間通信がホスト名で解決されます。これは本番環境のサービスディスカバリーに近い動作です。

## トラブルシューティングと運用のコツ

起動時に`depends_on`を指定していても、サービスの完全な準備ができていないことがあります。このような場合は、ヘルスチェックを追加します：

```yaml
db:
  image: postgres:15-alpine
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U appuser"]
    interval: 10s
    timeout: 5s
    retries: 5
```

また、複数人での開発時は、マイグレーションやシードデータの自動実行を`entrypoint.sh`で制御するのも良い方法です。

## まとめ

Docker Composeを活用することで、開発環境を本番に近づけることができます。これによりデプロイ前のトラブルを減らし、開発生産性を大幅に向上させることが可能です。最初の設定に時間がかかるかもしれませんが、チーム全体で一度構築すれば、その後の開発がスムーズになります。今からでも遅くありません。ぜひプロジェクトに導入してみてください。
