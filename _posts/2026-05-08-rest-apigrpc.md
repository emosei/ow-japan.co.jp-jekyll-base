---
layout: post
title: "REST APIとgRPCの共存時に『エラーハンドリング仕様の不統一』が運用コストを増やす理由"
date: 2026-05-08
categories: tech-tips
tags: []
author: OpenWorks
---

## はじめに──複数プロトコルの混在で見落とされる問題

マイクロサービス化やシステム刷新の過程で、既存のREST APIと新規のgRPCを並行運用する状況は珍しくありません。通信プロトコルを段階的に移行したい、あるいは用途に応じて使い分けたいという判断は合理的です。

しかし現場では、プロトコルの選択に注力する一方で、**エラーハンドリング仕様の統一に目が届かないケースが多く見られます**。REST APIはHTTPステータスコードとレスポンスボディで、gRPCはステータスコードと詳細メッセージで、それぞれ異なる形式でエラーを返すのが標準です。この違いが、運用フェーズで想定外のコストを生み出します。

本記事では、その理由と、実務で機能する統一戦略を紹介します。

## プロトコル間でエラー仕様が異なることの実害

### ログ解析と障害対応の複雑化

REST APIとgRPCが混在する環境では、エラーを検知するための監視ロジックが2つ以上必要になります。

REST APIでは、HTTPステータスコードの範囲（4xx、5xx）と、JSON レスポンスボディ内のエラーコード・メッセージで状況を判定します。一方gRPCでは、gRPCステータスコード（`OK`、`INVALID_ARGUMENT`、`INTERNAL` など）とメタデータ内のカスタム情報を組み合わせます。

```
// REST API の典型的なエラーレスポンス
{
  "error": {
    "code": "PAYMENT_FAILED",
    "message": "決済処理に失敗しました",
    "details": {
      "reason": "insufficient_balance",
      "retry_after_seconds": 60
    }
  }
}

// gRPC の典型的なエラー返却
status.Error(codes.FailedPrecondition, "insufficient_balance")
// メタデータで retry_after_seconds を別途付与
```

ログ集約システムやアラートルールを書く際、両方の形式に対応した解析ロジックが必要になり、保守が複雑になります。さらに、新しいエラーケースが発生した時、REST APIとgRPC両方で同じ意味のエラーを定義し直す手間が発生します。

### クライアント実装の分散と認識ずれ

フロントエンドチーム、モバイルチーム、バックエンド間のサービス通信など、複数の消費者がこれらのAPIを使う場合、エラーハンドリング仕様の認識がずれやすくなります。

REST APIではHTTP 429（Too Many Requests）で速度制限を示し、gRPCでは `RESOURCE_EXHAUSTED` を使う、といった具合です。同じビジネスロジック上のエラーなのに、クライアント側で異なるハンドリングコードを書くことになり、バグの温床になります。

実際の現場では、REST API用の再試行ロジックとgRPC用の再試行ロジックが微妙に異なり、片方では正常に復帰するが片方では失敗するという問題が起きやすいです。

### 運用チームの判断負荷と対応時間の延長

オンコール対応時に、「このエラーは重大か、それとも自動復帰するか」を判断する際、プロトコルごとにエラー仕様を確認する必要があります。本来なら共通の判断基準があれば1度の確認で済むところが、2度の確認が必要になり、対応時間が延びます。

特に夜間や休日の緊急対応では、この数分の差が顧客への影響を広げることもあります。

## 統一戦略：中間表現層を設ける

最も現実的な解決法は、**プロトコル層の下に、アプリケーション共通のエラー定義層を設ける**ことです。

### 設計の基本方針

1. **ドメイン層でエラーを定義する**：ビジネスロジック上のエラーを、プロトコルに依存しない形で定義します。
2. **プロトコルアダプタで変換する**：REST API、gRPCそれぞれのハンドラーで、ドメインエラーをプロトコル固有の形式に変換します。
3. **ロギングは統一フォーマットで**：どのプロトコルで発生したエラーでも、ログ出力時は共通フォーマットにします。

### 実装例

```go
// ドメイン層：プロトコル非依存のエラー定義
package domain

type ErrorCode string

const (
    ErrorInsufficientBalance    ErrorCode = "INSUFFICIENT_BALANCE"
    ErrorPaymentGatewayTimeout  ErrorCode = "PAYMENT_GATEWAY_TIMEOUT"
    ErrorInvalidRequest         ErrorCode = "INVALID_REQUEST"
)

type DomainError struct {
    Code       ErrorCode
    Message    string
    StatusCode int       // HTTP相当の一般的ステータス
    Retryable  bool
    Details    map[string]interface{}
}

// REST API ハンドラー層
package api

func (h *PaymentHandler) ProcessPayment(w http.ResponseWriter, r *http.Request) {
    // ビジネスロジック実行
    err := h.service.ProcessPayment(ctx, req)
    if err != nil {
        domainErr := err.(*domain.DomainError)
        
        w.Header().Set("Content-Type", "application/json")
        w.WriteHeader(domainErr.StatusCode)
        json.NewEncoder(w).Encode(map[string]interface{}{
            "error": map[string]interface{}{
                "code":      domainErr.Code,
                "message":   domainErr.Message,
                "details":   domainErr.Details,
            },
        })
        
        h.logger.LogError(domainErr)
        return
    }
}

// gRPC ハンドラー層
package grpc

func (s *PaymentService) ProcessPayment(ctx context.Context, req *pb.PaymentRequest) (*pb.PaymentResponse, error) {
    err := s.service.ProcessPayment(ctx, req)
    if err != nil {
        domainErr := err.(*domain.DomainError)
        
        // gRPCステータスコードへの変換
        grpcCode := mapToGRPCCode(domainErr.Code)
        
        // メタデータで詳細情報を付与
        md := metadata.Pairs(
            "error-code", string(domainErr.Code),
            "retryable", fmt.Sprintf("%v", domainErr.Retryable),
        )
        
        s.logger.LogError(domainErr)
        return nil, status.Error(grpcCode, domainErr.Message)
    }
}

// マッピング関数
func mapToGRPCCode(code domain.ErrorCode) codes.Code {
    switch code {
    case domain.ErrorInsufficientBalance:
        return codes.FailedPrecondition
    case domain.ErrorPaymentGatewayTimeout:
        return codes.DeadlineExceeded
    case domain.ErrorInvalidRequest:
        return codes.InvalidArgument
    default:
        return codes.Internal
    }
}
```

### ロギングの統一

```go
// ロギング層：プロトコルに依存しない統一フォーマット
package logging

type ErrorLog struct {
    Timestamp   time.Time              `json:"timestamp"`
    Code        domain.ErrorCode       `json:"error_code"`
    Message     string                 `json:"message"`
    Retryable   bool                   `json:"retryable"`
    Protocol    string                 `json:"protocol"` // "rest" or "grpc"
    Details     map[string]interface{} `json:"details"`
}

func (l *Logger) LogError(err *domain.DomainError, protocol string) {
    errorLog := ErrorLog{
        Timestamp: time.Now(),
        Code:      err.Code,
        Message:   err.Message,
        Retryable: err.Retryable,
        Protocol:  protocol,
        Details:   err.Details,
    }
    // JSON形式で出力
    l.output(errorLog)
}
```

この構造にすると、監視ルールやアラート設定は `error_code` フィールドだけを見れば良くなり、プロトコルの違いに左右されません。

## 運用時に気をつけるポイント

### エラーコード定義の追加時ルール

新しいエラーケースが発生した場合、以下の順序で対応します：

1. ドメイン層に `ErrorCode` を追加
2. REST API、gRPC両方のマッピング関数を更新
3. ロギングテンプレートが対応していることを確認
4. 監視ルールを更新（必要に応じて）

この流れを徹底しないと、REST APIでは新しいエラーが返っているのにgRPCではまだ古い形式のままという不整合が起きます。

### 既存APIの段階的統一

全てを一度に統一するのは現実的ではないため、以下のような段階を踏むことをお勧めします：

- **第1段階**：新規開発するエンドポイントから統一フォーマットを適用
- **第2段階**：高頻度で呼ばれるエンドポイントから順に統一
- **第3段階**：レガシーエンドポイントは互換性レイヤーを設けて対応

互換性レイヤーでは、古い形式のレスポンスを新しい統一形式に変換し、ログには統一形式で出力するようにします。

### テスト戦略の工夫

REST APIとgRPC両方でエラーケースをテストする際、テストケースの定義を共有化します：

```go
// 共通のエラーテストケース定義
var errorTestCases = []struct {
    name          string
    errorCode     domain.ErrorCode
    expectedHTTP  int
    expectedGRPC  codes.Code
    retryable     bool
}{
    {
        name:         "insufficient_balance",
        errorCode:    domain.ErrorInsufficientBalance,
        expectedHTTP: http.StatusPaymentRequired,
        expectedGRPC: codes.FailedPrecondition,
        retryable:    false,
    },
    // ...
}
```

このテーブルを使ってREST APIテストとgRPCテスト両方を駆動することで、仕様のずれを早期に検出できます。

## 小規模チームでの導入ステップ

1. **まずドメイン層のエラー定義を整理**：現在のプロトコル間で、同じ意味のエラーを洗い出し、統一名を決める
2. **新規機能から適用**：既存コードの大規模リファクタリングは
