---
layout: post
title: "ネイティブアプリとWebViewの混在時に生じるセッション管理の複雑性──Cookie・認証トークン・ストレージの三者関係"
date: 2026-05-04
categories: tech-tips
tags: []
author: OpenWorks
---

## 現場で起きる「認証が効かない」の正体

モバイルアプリの開発で、ネイティブ部分とWebView部分が混在するとき、セッション管理は予想外に複雑になります。特に厄介なのは「ネイティブ側では認証済みなのに、WebViewを開くと再ログインを求められる」といった現象です。

これは単なるバグではなく、ブラウザのセッション機構とアプリ内通信の仕様が根本的に異なることから生じる設計課題です。ネイティブコードからHTTPリクエストを送るときと、WebViewが送るときでは、Cookieの扱い、トークンの保存先、そして有効期限の判定ロジックが一貫していないことがほとんどです。

実装段階では「とりあえず動く」状態で済ませやすいのですが、運用に入ると、ユーザーが予測不能なタイミングで認証エラーに遭遇し、ログイン画面に戻されるという問題が頻出します。

## Cookie依存の設計が機能しない理由

従来のWebアプリケーションでは、サーバーがSet-Cookieヘッダーでブラウザにセッションクッキーを発行し、以降のリクエストで自動的にそれが送信される仕組みでした。この「自動送信」がWebViewでも同じように動くと考えるのが落とし穴です。

ネイティブアプリからHTTPリクエストを送る場合、多くのHTTPクライアントライブラリはデフォルトでCookieを無視するか、アプリケーション側で明示的に有効化する必要があります。さらに、ネイティブ側で送ったリクエストで取得したセッションクッキーと、WebViewが持つクッキーストレージは物理的に分離していることがあります。

```
ネイティブHTTPクライアント（例：URLSession、OkHttp）
  ↓ Cookieストア A
  └─ サーバー

WebView（UIWebView、WKWebView、WebView）
  ↓ Cookieストア B
  └─ サーバー
```

ネイティブ側で取得したセッションクッキーがストア Aに保存されても、WebViewはストア B を参照するため、WebView内のリクエストにはそのクッキーが含まれません。結果、WebView側から見ると「認証されていない状態」になります。

## 認証トークンをどこに置くか──三つの選択肢と現実的な制約

セッション管理を統一するには、Cookieに頼らず、認証トークン（JWT、OAuth 2.0のアクセストークンなど）をアプリケーション層で管理する方法が一般的です。ただし「どこに置くか」という選択が、セキュリティと利便性のトレードオフを生み出します。

### ローカルストレージ（LocalStorage）

JavaScriptからアクセス可能なローカルストレージにトークンを保存する方法です。ネイティブ側でも `evaluateJavaScript` や同等の機能でアクセスできます。

**メリット**：実装が簡単、ネイティブとWebViewの両方から読み書き可能

**デメリット**：XSS攻撃に対して脆弱。注入されたJavaScriptからトークンが盗まれる可能性があります。実務では「XSSが起きない設計」を前提にしがちですが、サードパーティライブラリの脆弱性や、運用中の予期しない入力値処理ミスから発生することはあります。

### セキュアストレージ（Keychain/Keystore）

iOSのKeychain、AndroidのKeystoreといったOS提供のセキュアストレージにトークンを保存します。これはネイティブコードからのみアクセス可能です。

**メリット**：OSレベルで暗号化・保護されており、セキュリティが高い

**デメリット**：WebView側からは直接アクセスできないため、トークンをWebViewに渡す際に中間層を経由する必要があります。この「渡し方」が複雑になります。

### HttpOnly Cookie（サーバー側で設定）

サーバーがSet-Cookieヘッダーで `HttpOnly` フラグを付けてCookieを発行すれば、JavaScriptからはアクセス不可になり、XSS対策になります。ただしこれは「WebViewとネイティブの両方が同じCookieストアを使う」ことが前提です。

**実装上の注意**：ネイティブHTTPクライアントがCookie自動送信に対応していることを確認し、WebViewも同じCookieストアを参照するよう設定する必要があります。

```swift
// iOS WKWebView の例
let config = WKWebViewConfiguration()
let dataStore = WKWebsiteDataStore.default()
config.websiteDataStore = dataStore
let webView = WKWebView(frame: .zero, configuration: config)

// ネイティブ側のURLSessionも同じCookieストアを参照
let sharedCookies = HTTPCookieStorage.shared
var request = URLRequest(url: url)
request.httpShouldHandleCookies = true
```

しかし実際には、ネイティブのHTTPクライアントとWebViewが「本当に同じCookieストアを参照しているか」を検証することは意外と難しく、OSバージョンやライブラリの更新で挙動が変わることもあります。

## 実装上の現実的な判断

小規模なチームで運用を考えると、以下のような優先度で判断することをお勧めします。

### 1. 認証トークンをネイティブのセキュアストレージに保持する

ネイティブ側のKeychain/Keystoreに認証トークンを保存し、WebView内のリクエストには、ネイティブ層を経由してトークンを注入します。

```swift
// ネイティブ側でトークンを取得
let token = try keychainManager.retrieveToken()

// WebViewに遷移する前に、JavaScriptで初期化
let script = "window.authToken = '\(token)';"
webView.evaluateJavaScript(script) { _, error in
    if let error = error {
        print("Failed to inject token: \(error)")
    }
}
```

WebView内のJavaScriptでは、そのトークンを使ってAPIリクエストのAuthorizationヘッダーに含めます。

```javascript
// WebView内のJavaScript
fetch('/api/resource', {
  headers: {
    'Authorization': 'Bearer ' + window.authToken
  }
})
```

**利点**：トークンはセキュアストレージで保護され、WebViewに注入されたトークンはページ遷移時にクリアできる

**課題**：WebViewのページ遷移後、トークンが失われるため、再度ネイティブ層を経由して注入する必要があります。ユーザーが手動でリロードした場合の対応も考慮が必要です。

### 2. トークンの有効期限と更新戦略を明確にする

セッション管理の複雑さを軽減するには、トークンの有効期限を短くし、更新（リフレッシュ）の仕組みを用意することが重要です。

- **アクセストークン**：短命（15分～1時間）
- **リフレッシュトークン**：長命（数日～数週間）、セキュアストレージに保存

アクセストークンが期限切れの場合、リフレッシュトークンを使って新しいアクセストークンを取得します。この処理はネイティブ層で一元管理することで、ネイティブ・WebView双方で一貫性を保ちやすくなります。

### 3. WebView内で認証エラーが発生したときの回復フロー

WebView内のリクエストが401（Unauthorized）を返した場合、単にログイン画面に遷移するのではなく、まずネイティブ層に通知してトークン更新を試みるべきです。

```javascript
// WebView内のAPIレイヤー
async function apiCall(endpoint, options = {}) {
  let response = await fetch(endpoint, options);
  
  if (response.status === 401) {
    // ネイティブ層にトークン更新を依頼
    if (window.webkit && window.webkit.messageHandlers) {
      window.webkit.messageHandlers.refreshToken.postMessage({});
      // 更新後、リトライ
      response = await fetch(endpoint, options);
    }
  }
  
  return response;
}
```

ネイティブ側でメッセージを受け取り、トークンを更新してからWebViewに通知します。

```swift
// WKScriptMessageHandler の実装
func userContentController(
  _ userContentController: WKUserContentController,
  didReceive message: WKScriptMessage
) {
  if message.name == "refreshToken" {
    // トークン更新処理
    refreshToken { success in
      if success {
        // 更新成功をWebViewに通知
        let script = "window.onTokenRefreshed();"
        webView.evaluateJavaScript(script)
      }
    }
  }
}
```

## 運用時に見落としやすい落とし穴

### ローカルストレージのクリア

ユーザーがアプリの「キャッシュをクリア」操作を実行したとき、ローカルストレージも削除されるOSがあります。その結果、トークンが消失してログアウト状態になります。セキュアストレージに保存したトークンは保護されるため、この問題は起きません。

### トークンのリークと有効期限の延長

「ユーザーが頻繁にログアウトされる」という苦情に対して、有効期限を無制限に延長するのは避けるべきです。代わりにリフレッシュトークンの有効期限を延ばすか、バックグラウンドでの自動更新を実装してください。

### テスト環境での認証トークンの扱い

開発・テスト環境では、認証をバイパスしたい場合があります。この場合、ネイティブ側で環境判定を行い、テスト用のダミートークンを注入する仕組みを用意すると、テストが楽になります。ただし本番環境では確実に無効化してください。

## 小規模チームでの導入ステップ

1. **認証方式を決定する**：JWT、OAuth 2.0など、サーバー側の実装と合わせて選定
2. **トークン保存先を統一する**：セキュアストレージ（推奨）またはHttpOnly Cookie
3
