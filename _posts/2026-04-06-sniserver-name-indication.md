---
layout: post
title: "SNI（Server Name Indication）とは？"
date: 2026-04-06
categories: tech-verification
tags: ["HTTPS", "TLS/SSL", "SNI", "Nginx", "サーバー設定"]
author: OpenWorks
---

# SNI（Server Name Indication）とは？複数のHTTPSサイトを1つのIPアドレスでホストする技術

## はじめに

Webサイトを運営していると、複数のドメインを同じサーバーで管理する場面が増えてきました。しかし、HTTPS通信では、従来の方法では1つのIPアドレスに対して1つのSSL/TLSサーティフィケートしか割り当てられないという課題がありました。

この課題を解決するのが「SNI（Server Name Indication）」という技術です。本記事では、SNIの仕組みや実務での活用方法についてご紹介します。

## SNIの基本概念

SNIは、TLS/SSL通信の初期段階で、クライアントがアクセスしたいドメイン名をサーバーに送信する仕組みです。

通常、HTTPSで通信を開始する際、TLSハンドシェイクが行われます。この過程で、サーバーはクライアントにSSL/TLSサーティフィケートを提示します。SNI導入以前は、この時点でサーバーはIPアドレスからしか判定できず、複数ドメインに対応する場合、追加のIPアドレスが必要でした。

SNIが登場することで、クライアントからのTLSハンドシェイク段階で「example.com」「sample.jp」といったドメイン情報が事前に送信されます。サーバーはこれを受け取り、該当するサーティフィケートを返す—これが実現できるようになったのです。

## SNI導入のメリット

### コスト削減

最大のメリットは**IPアドレスの節約**です。従来は複数ドメインでHTTPSを使う場合、各ドメインごとにIPアドレスが必要でした。SNIにより、1つのIPアドレスで複数のドメインをホストできるため、サーバーコストを大幅に削減できます。

### 運用の簡素化

複数ドメイン管理時の設定が単純化されます。わざわざIPアドレスを追加したり、DNSレコードを増やしたりする必要がなくなります。

## 実務での活用方法

### Nginxの設定例

Nginxでは、SNIに対応した設定が比較的簡単です：

```nginx
server {
    listen 443 ssl;
    server_name example.com;
    
    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;
    # 設定省略
}

server {
    listen 443 ssl;
    server_name sample.jp;
    
    ssl_certificate /etc/ssl/certs/sample.jp.crt;
    ssl_certificate_key /etc/ssl/private/sample.jp.key;
    # 設定省略
}
```

複数の`server`ブロックで異なるドメインと証明書を指定するだけで、SNIが自動的に機能します。

### Apache HTTPDの設定例

```apache
<VirtualHost *:443>
    ServerName example.com
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/example.com.crt
    SSLCertificateKeyFile /etc/ssl/private/example.com.key
</VirtualHost>

<VirtualHost *:443>
    ServerName sample.jp
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/sample.jp.crt
    SSLCertificateKeyFile /etc/ssl/private/sample.jp.key
</VirtualHost>
```

Apacheでも同様に複数のVirtualHostで対応できます。

## 注意点とベストプラクティス

### ブラウザ互換性

SNIはほぼ全てのモダンブラウザで対応していますが、**古いAndroidデバイス（4.1以下）やInternet Explorer 8以前**では対応していません。ユーザー層によっては考慮が必要です。

### ワイルドカードサーティフィケートの活用

複数のサブドメインを管理する場合、ワイルドカード証明書（*.example.com）の利用も検討するとよいでしょう。SNIと組み合わせることで、さらに柔軟な構成が可能になります。

## まとめ

SNIはHTTPS時代の必須技術であり、複数ドメイン運用時のコスト削減と運用効率化を実現します。既に多くのレンタルサーバーやクラウドサービスが対応しており、新規プロジェクトではSNI対応が標準となっています。

特にマイクロサービス構成やマルチテナント環境では、SNIの活用が重要な要素になってきます。まだ導入していない方は、この機会に検討してみてはいかがでしょうか。
