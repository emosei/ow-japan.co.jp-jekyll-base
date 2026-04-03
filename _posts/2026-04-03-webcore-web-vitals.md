---
layout: post
title: "Webアプリのパフォーマンス計測と改善：Core Web Vitals実践ガイド"
date: 2026-04-03
categories: tech-tips
tags: ["Web パフォーマンス", "Core Web Vitals", "SEO", "フロントエンド最適化", "ユーザー体験"]
author: OpenWorks
---

# Webアプリのパフォーマンス計測と改善：Core Web Vitals実践ガイド

Webアプリのパフォーマンスは、ユーザー体験に直結する重要な要素です。しかし「何を計測すればいいのか」「どうやって改善するのか」といった課題を抱えている方も多いのではないでしょうか。そこで活躍するのが**Google が推奨する「Core Web Vitals」**という指標です。本記事では、Core Web Vitals の基礎から実践的な改善方法までを解説します。

## Core Web Vitals とは何か

Core Web Vitals（コアウェブバイタルズ）は、Webページのユーザー体験を定量的に評価するため、Googleが2020年に導入した3つの主要指標です。

**LCP（Largest Contentful Paint）**
ページの読み込み速度を示す指標で、メインコンテンツが画面に表示されるまでの時間を計測します。目標は2.5秒以下です。画像の遅延やサーバー応答時間の遅さが原因となることが多いです。

**FID（First Input Delay）**
ユーザーがボタンをクリックやキー入力した際のレスポンス時間を計測します。目標は100ミリ秒以下です。JavaScriptの処理が重いと悪化します。なお、2024年以降はINP（Interaction to Next Paint）に置き換わる予定です。

**CLS（Cumulative Layout Shift）**
ページ表示中に予期しないレイアウトのズレが生じる度合いを計測します。目標は0.1以下です。広告の遅延読み込みが原因になるケースが典型的です。

これら3つの指標は、GoogleのSEO評価にも影響するため、ビジネス面でも重要です。

## 計測方法：ツール活用のポイント

Core Web Vitals を計測するには、複数のツールが活用できます。

**Google PageSpeed Insights**
最も手軽に始められるツールです。URLを入力するだけで、デスクトップ・モバイル両環境でのスコアが得られます。改善提案も自動で提示されるため、初心者向けです。

**Chrome DevTools**
ブラウザの開発者ツールで、実際のユーザー環境に近いデータを計測できます。以下のコマンドでパフォーマンス情報を取得することも可能です。

```javascript
const observer = new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) {
    console.log('LCP:', entry.startTime);
  }
});
observer.observe({entryTypes: ['largest-contentful-paint']});
```

**Web Vitals ライブラリ**
Googleが提供する公式JavaScriptライブラリを導入すれば、本番環境での実際のユーザーデータ（RUM：Real User Monitoring）を収集できます。

```javascript
import {getCLS, getFID, getFCP, getLCP, getTTFB} from 'web-vitals';

getCLS(console.log);
getLCP(console.log);
getFID(console.log);
```

## 改善アクション：実践的な対策

計測ツールで問題が見つかったら、以下の改善アクションに取り組みましょう。

**LCP の改善**
- 画像の最適化：次世代フォーマット（WebP）やレスポンシブ画像を活用
- サーバーの高速化：CDNの導入やキャッシュ戦略の見直し
- 不要なJavaScriptの削除：バンドルサイズを圧縮

**FID/INP の改善**
- メインスレッドの負荷軽減：重い処理をWeb Workersに移行
- JavaScriptの分割読み込み：Code Splittingで初期ロード時間を短縮
- サードパーティスクリプトの最適化：外部ライブラリの遅延読み込み

**CLS の改善**
- 要素の予約スペース確保：画像やメディア要素に固定のサイズを指定
- フォント読み込みの最適化：`font-display: swap` で無視可能なテキストの表示遅延を防止
- 広告枠の制御：レイアウトシフトを引き起こす動的要素の事前予約

これらの改善は段階的に進めることをお勧めします。まずは最もスコアが低い指標から着手し、効果を検証してから次のアクションに移る方法が効率的です。

## まとめ

Core Web Vitals はWebアプリのパフォーマンス改善を進める上での羅針盤となります。Google PageSpeed Insights などのツールで現状を把握し、LCP・FID・CLS の各指標に対して優先順位をつけて取り組むことが重要です。

パフォーマンス改善は一度実施すれば終わりではなく、継続的に計測・改善を繰り返すプロセスです。ぜひ貴社のWebアプリでもこのガイドを参考に、ユーザー体験の向上に取り組んでいただきたいと思います。
