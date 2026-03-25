---
layout: post
title: "Docker Composeで整える快適なローカル開発環境"
date: 2026-03-25
categories: tech-tips
tags: ["Docker", "Docker Compose", "開発環境", "ローカル開発", "インフラ"]
author: OpenWorks
---

# Docker Composeで整える快適なローカル開発環境

開発を進める際、「ローカル環境のセットアップに時間がかかる」「チームメンバーの環境が異なる」といった課題に直面することはありませんか？そんな悩みを解決する強い味方が**Docker Compose**です。本記事では、実務で役立つDocker Composeの活用方法をご紹介します。

## Docker Composeってそもそも何？

Docker Composeは、複数のDockerコンテナを簡単に管理するツールです。Webアプリケーション開発では、データベース、キャッシュサーバー、Webサーバーなど複数のサービスが必要になります。これらを個別に起動・停止するのは手間ですが、Compose設定ファイル（docker-compose.yml）に記述しておくと、1つのコマンドで全サービスを起動できます。

開発環境を構築した経験がある方なら、データベースのインストール、依存関係の解決、バージョン管理など、様々な手作業を思い出すでしょう。Docker Composeを使えば、これらの煩雑な作業を大幅に削減でき、**「環境がコード化される」メリット**が得られます。

## docker-compose.ymlで開発環境を定義する

まずは基本となるymlファイルを作成してみましょう。以下は、Node.js + PostgreSQL + Redisという構成例です。

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "3000:3000"
    depends_on:
      - db
      - redis
    environment:
      - DATABASE_URL=postgresql://user:password@db:5432/myapp
      - REDIS_URL=redis://redis:6379
    volumes:
      - .:/app
    command: npm run dev

  db:
    image: postgres:14
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=myapp
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

このファイルを同じディレクトリに置き、`docker-compose up`を実行するだけで、3つのサービスが立ち上がります。シンプルですね。

## 実務で活躍する3つの機能

### ボリュームマウントで効率的に開発する

上記の例で注目すべきは、webサービスの`volumes`設定です。

```yaml
volumes:
  - .:/app
```

この1行により、ホスト側のカレントディレクトリがコンテナ内の/appにマウントされます。つまり、ローカルのテキストエディタで編集したファイルが即座にコンテナに反映されるため、わざわざイメージをビルドし直す必要がありません。開発効率が劇的に向上します。

### 環境変数で異なる環境に対応

`environment`キーで環境変数を設定できます。本番環境とローカル開発環境で異なる設定が必要な場合は、`.env`ファイルを別途作成し、`env_file`で読み込む方法も便利です。

```yaml
env_file:
  - .env.development
```

### depends_onでサービス間の依存関係を管理

`depends_on`を指定すると、指定したサービスが起動してから他のサービスが起動します。これにより、「データベースの準備ができる前にWebアプリが起動する」といったトラブルを防げます。

## よくある活用シーン

**シーン1: 新しいメンバーのオンボーディング**  
設定ファイルをGitで共有すれば、新しいエンジニアは`docker-compose up`1つで同じ環境を構築できます。セットアップ時間が大幅に短縮され、実装に素早く取り掛かれます。

**シーン2: バージョン間の動作確認**  
PostgreSQLのバージョンを変更して動作を確認したい場合、ymlファイルの`image`タグを変更するだけです。コンテナを削除して新しいバージョンで再起動できます。

**シーン3: 本番環境との差分を最小化**  
開発環境と本番環境を同じDocker設定で構築することで、「ローカルでは動くが本番では動かない」といった環境依存のバグを大幅に減らせます。

## まとめ

Docker Composeは、ローカル開発環境をコード化し、チーム全体で統一された環境を実現する強力なツールです。初期の設定は少し学習が必要ですが、一度構築すれば、開発効率の向上、オンボーディング時間の短縮、環境起因のバグ減少といった多くのメリットが得られます。

まだ導入していない方は、ぜひこの機会に試してみてください。最初は簡単な構成から始めて、プロジェクトに応じてカスタマイズしていくことをお勧めします。

---
