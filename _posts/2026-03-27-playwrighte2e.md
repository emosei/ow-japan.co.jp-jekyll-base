---
layout: post
title: "PlaywrightでE2Eテストを書いてみた"
date: 2026-03-27
categories: tech-verification
tags: ["Playwright", "E2Eテスト", "テスト自動化", "ブラウザオートメーション", "JavaScript"]
author: OpenWorks
---

# PlaywrightでE2Eテストを書いてみた

## はじめに

Webアプリケーション開発において、ユーザーが実際に操作するシナリオをテストするE2E（End to End）テストは非常に重要です。これまでSeleniumやCypressなどを使用してきたエンジニアの方も多いと思いますが、今回は「Playwright」を使ったE2Eテストの実装を試してみました。

Playwrightは、Microsoftによるオープンソースのブラウザオートメーションツールであり、Chrome、Firefox、WebKitの複数ブラウザに対応しています。実際に導入してみた感想をお伝えします。

## Playwrightを選んだ理由

Playwrightの大きな特徴は**複数ブラウザの同時テスト対応**と**高速性**です。設定ファイル一つでChrome、Firefox、Safari互換のWebKitで並行実行できます。これまでのツールと比べてセットアップが簡単で、ドキュメントも充実しており、初心者でも導入しやすい点が魅力的でした。

また、クロスプラットフォーム対応で、Windows、Mac、Linux環境で同じテストコードを実行できることも、チーム開発に適していると感じました。

## 実装してみた

### 環境構築

まずはインストールから始めます。

```bash
npm install -D @playwright/test
npx playwright install
```

プロジェクトに必要な依存関係をインストールし、ブラウザバイナリもダウンロードされます。その後、設定ファイル `playwright.config.ts` を作成します。

```typescript
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },
  ],
});
```

### 実際のテスト例

ログイン機能を例にテストコードを書いてみました。

```typescript
import { test, expect } from '@playwright/test';

test('ログイン成功時のテスト', async ({ page }) => {
  // ページへアクセス
  await page.goto('/login');

  // メールアドレスとパスワードを入力
  await page.fill('input[name="email"]', 'test@example.com');
  await page.fill('input[name="password"]', 'password123');

  // ログインボタンをクリック
  await page.click('button:has-text("ログイン")');

  // ダッシュボードにリダイレクトされたことを確認
  await expect(page).toHaveURL('/dashboard');

  // ウェルカムメッセージが表示されていることを確認
  await expect(page.locator('text=ようこそ')).toBeVisible();
});

test('不正な認証情報でのテスト', async ({ page }) => {
  await page.goto('/login');
  await page.fill('input[name="email"]', 'test@example.com');
  await page.fill('input[name="password"]', 'wrongpassword');
  await page.click('button:has-text("ログイン")');

  // エラーメッセージが表示されることを確認
  await expect(page.locator('text=認証に失敗しました')).toBeVisible();
});
```

## 実装の所感

### メリット

最初に感じたのは**可読性の高さ**です。セレクタの指定が直感的で、複雑なページ操作も わかりやすくコード化できます。また、テスト実行時に自動的に動画やスクリーンショットを記録してくれるため、失敗時の原因究明が容易でした。

実行速度も期待以上に速く、複数のテストを並行実行しても十分実用的です。さらに、CI/CDパイプラインへの組み込みもシンプルで、GithubActionsなどとの連携も スムーズでした。

### デメリット

少し挙げるとすれば、エコシステムの拡張性です。プラグインやカスタマイズのオプションはCypressに比べて限定的という印象は持ちました。ただ、基本的な機能は十分充実しており、ほとんどのユースケースはカバーできます。

## まとめ

Playwrightは、E2Eテスト初心者からベテランのエンジニアまで、幅広い層におすすめできるツールです。複数ブラウザ対応の設定が簡単で、テストコードの可読性も優れています。

これからWebアプリケーション開発をより堅牢にしたいとお考えでしたら、一度Playwrightの導入を検討してみることをお勧めします。
