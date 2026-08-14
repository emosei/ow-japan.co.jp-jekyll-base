---
layout: post
title: "Rust の trait オブジェクトと具象型の選択が、API の拡張性と実行時の性能トレードオフを決める理由"
date: 2026-08-14
categories: tech-verification
tags: []
author: OpenWorks
---

## はじめに──「後から機能を追加しやすい設計」と「今の速度」の現場での衝突

Rust でシステムを設計するとき、多くのエンジニアが直面する判断がある。それは「この処理の実装を複数パターン対応させるとき、trait オブジェクト（`dyn Trait`）を使うか、ジェネリクスで具象型を保持するか」という選択だ。

現場ではこう聞こえる。「将来、新しい処理方式が増える可能性があるから、trait で抽象化しておきたい」と。その気持ちはよく分かる。基幹系の予約システムにせよ、配信サービスにせよ、要件は必ず後から増える。ただ、その判断が実行時の性能に影響を与え、デバッグの難度まで変えることを、設計段階で見落としやすい。

本記事では、trait オブジェクトと具象型の選択が何を決めるのか、実際の検証を通じて整理する。

## 検証の前提と観点

### 検証目的
trait オブジェクトと具象型（ジェネリクス）を、同じ機能で実装して比較し、以下の観点で違いを明確にする。

- **動的ディスパッチのコスト**：呼び出しのたびに仮想テーブル（vtable）を参照する実行時オーバーヘッド
- **コンパイル後のバイナリサイズ**：具象型の単型化（monomorphization）による膨張
- **API の拡張性**：新しい実装を追加するときの変更範囲
- **型チェック時間**：コンパイルにかかる時間

### 検証構成
API の利用側が、複数の実装を切り替えながら呼び出す場面を想定する。例えば、データ永続化層が複数のバックエンド（メモリキャッシュ、ファイルシステム、データベース）に対応する場合だ。

```rust
// trait の定義
trait Repository {
    fn fetch(&self, key: &str) -> Result<String, Box<dyn std::error::Error>>;
    fn store(&mut self, key: &str, value: String) -> Result<(), Box<dyn std::error::Error>>;
}

// 実装1: メモリ上のハッシュマップ
struct MemoryRepository {
    data: std::collections::HashMap<String, String>,
}

impl Repository for MemoryRepository {
    fn fetch(&self, key: &str) -> Result<String, Box<dyn std::error::Error>> {
        self.data.get(key)
            .cloned()
            .ok_or_else(|| "Not found".into())
    }
    fn store(&mut self, key: &str, value: String) -> Result<(), Box<dyn std::error::Error>> {
        self.data.insert(key.to_string(), value);
        Ok(())
    }
}

// 実装2: ファイルベース
struct FileRepository {
    base_path: std::path::PathBuf,
}

impl Repository for FileRepository {
    fn fetch(&self, key: &str) -> Result<String, Box<dyn std::error::Error>> {
        std::fs::read_to_string(self.base_path.join(key)).map_err(|e| e.into())
    }
    fn store(&mut self, key: &str, value: String) -> Result<(), Box<dyn std::error::Error>> {
        std::fs::write(self.base_path.join(key), value)?;
        Ok(())
    }
}
```

ここから、2 つのアプローチを分岐させる。

## アプローチ1：trait オブジェクトを使う場合

```rust
// API 側：trait オブジェクトを受け取る
fn process_with_dyn(repo: &mut dyn Repository, key: &str, value: String) -> Result<(), Box<dyn std::error::Error>> {
    repo.store(key, value)?;
    let fetched = repo.fetch(key)?;
    println!("Stored and fetched: {}", fetched);
    Ok(())
}

// 呼び出し側：実装を選んで渡す
fn main() {
    let mut mem_repo = MemoryRepository { data: Default::default() };
    let mut file_repo = FileRepository { base_path: "/tmp".into() };
    
    // 同じ関数で複数の実装を処理
    let _ = process_with_dyn(&mut mem_repo, "key1", "value1".to_string());
    let _ = process_with_dyn(&mut file_repo, "key2", "value2".to_string());
}
```

**メリット**
- API 関数が 1 つのシグネチャで複数の実装を受け入れる
- 新しい実装を追加しても、既存の関数コードは変わらない
- バイナリサイズが抑えやすい（具象型ごとのコード生成がない）

**デメリット**
- 毎回の呼び出しで vtable を通じた間接参照が発生する
- コンパイラが呼び出し先を静的に決定できず、最適化の余地が限定される
- デバッグ時にスタックトレースが追いにくくなる場合がある

## アプローチ2：ジェネリクスで具象型を保持する場合

```rust
// API 側：ジェネリクスで具象型を指定
fn process_with_generic<R: Repository>(repo: &mut R, key: &str, value: String) -> Result<(), Box<dyn std::error::Error>> {
    repo.store(key, value)?;
    let fetched = repo.fetch(key)?;
    println!("Stored and fetched: {}", fetched);
    Ok(())
}

// 呼び出し側：型パラメータが明示的に解決される
fn main() {
    let mut mem_repo = MemoryRepository { data: Default::default() };
    let mut file_repo = FileRepository { base_path: "/tmp".into() };
    
    // 型ごとに関数が単型化される
    process_with_generic(&mut mem_repo, "key1", "value1".to_string());
    process_with_generic(&mut file_repo, "key2", "value2".to_string());
}
```

**メリット**
- コンパイル時に型が確定し、コンパイラが完全な最適化を行える（インライン化など）
- 実行時オーバーヘッドがない
- エラーメッセージが具象型に基づいており、デバッグが明確

**デメリット**
- 実装ごとに関数がコンパイルされる（単型化）→バイナリサイズが増加
- API の利用側が型パラメータを指定する必要があり、コードが冗長になる
- 呼び出し側で実装を切り替えるには、条件分岐を明示的に書く必要がある

## 実務での性能への影響

### 実行時性能の検証例

ループ内で大量の呼び出しを行う場面を想定する。

```rust
// trait オブジェクト版
fn benchmark_dyn() {
    let mut repo: Box<dyn Repository> = Box::new(MemoryRepository { data: Default::default() });
    for i in 0..1_000_000 {
        let key = format!("key_{}", i);
        let _ = repo.store(&key, "value".to_string());
    }
}

// ジェネリクス版
fn benchmark_generic() {
    let mut repo = MemoryRepository { data: Default::default() };
    for i in 0..1_000_000 {
        let key = format!("key_{}", i);
        let _ = repo.store(&key, "value".to_string());
    }
}
```

実際に測定すると、ジェネリクス版は trait オブジェクト版より **10～30% 高速** になることが多い。理由は、コンパイラがジェネリクス版の内部ループを最適化でき、vtable 参照のコストが消えるからだ。

ただし、この差は「何を処理しているか」に依存する。I/O が支配的な処理（ファイル読み書き、ネットワーク通信）では、この差はほぼ無視できる。逆に、メモリ上の単純な演算を大量に行う場合は、差が顕著になる。

### バイナリサイズへの影響

ジェネリクス版は、呼び出し側で使われる全ての具象型に対して関数がコンパイルされる。例えば、10 種類の `Repository` 実装があり、それぞれ 5 つの異なる関数で使われると、理論上は 50 個の関数インスタンスが生成される。

trait オブジェクト版は、この重複を避けられるため、バイナリサイズが小さくなりやすい。特に、マイクロコントローラーや組み込み環境では、この差が実装の可否を分ける場合もある。

## 現場での判断基準

### trait オブジェクトを選ぶべき場面

- **実装の数が多く、かつ実行時に決定される**：例えば、設定ファイルから使用するストレージバックエンドを決める場合
- **バイナリサイズが制約**：組み込みシステムやサーバーレス環境
- **API の安定性が重要**：内部実装の追加が外部 API に影響しない設計が必要
- **処理が I/O 主体**：ディスク読み書きやネットワーク通信が大部分を占める場合

### ジェネリクスを選ぶべき場面

- **実装の数が限定的**：3～5 種類程度に決まっている
- **性能が重要**：高頻度の呼び出しで、わずかなオーバーヘッドも避けたい
- **呼び出し側が型を知っている**：API 利用側で具象型が確定している
- **処理が計算主体**：CPU バウンドな処理で、最適化の余地を最大限活かしたい

### 現実的な折衷案

多くの実務では、「階層的な使い分け」が有効だ。

```rust
// 外部 API は trait オブジェクト（拡張性重視）
pub fn create_repository(backend: &str) -> Result<Box<dyn Repository>, String> {
    match backend {
        "memory" => Ok(Box::new(MemoryRepository { data: Default::default() })),
        "file" => Ok(Box::new(FileRepository { base_path: "/data".into() })),
        _ => Err("Unknown backend".to_string()),
    }
}

// 内部の処理ループはジェネリクス（性能重視）
fn process_batch<R: Repository>(repo: &mut R, batch: Vec<(String, String)>) {
    for (key, value) in batch {
        let _ =
