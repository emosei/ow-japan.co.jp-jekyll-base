---
layout: post
title: "RustのFFIでC言語ライブラリを呼ぶとき、unsafeの外側で起きるメモリ破壊──検証と監視の落とし穴"
date: 2026-06-22
categories: tech-verification
tags: ["Rust", "FFI", "メモリ安全性", "unsafe", "ライブラリ検証"]
author: OpenWorks
---

## Rustの「安全性の約束」が外部ライブラリで機能しない現実

Rustで既存のC言語ライブラリを呼び出す必要が生じたとき、多くのエンジニアは `unsafe` ブロックを書く。Rustの型システムやメモリ管理は強力だが、FFI（Foreign Function Interface）を使う瞬間、その保証は一気に脆くなります。

問題は単純です。C言語ライブラリが返したポインタが本当に有効か、確保したメモリが適切に解放されているか、バッファオーバーフローが発生していないか──こうした検証をRustのコンパイラは **できません**。`unsafe` ブロックの外側で、静かに、予測不可能な形で破壊が進行します。

現場では、このギャップに気づくのが遅れることが多いです。テストが通り、開発環境で動き、本番に出して数日後に異常が発生する。その時点では、どの外部ライブラリ呼び出しが原因か、追跡が難しくなっています。

## unsafe ブロックは「責任の移譲」であって「安全の保証」ではない

Rustのドキュメントでは、`unsafe` ブロックは「このコードが安全であることを保証するのはプログラマの責任」と明記されています。しかし現実の案件では、この「責任」の範囲が曖昧なまま進行することがあります。

例えば、こんな場面です：

```rust
unsafe {
    let ptr = c_library_allocate(size);
    if ptr.is_null() {
        return Err("allocation failed");
    }
    // ここまではいい。だが、このポインタは本当に有効か？
    // c_library_allocate が内部で何をしているか、ドキュメントに書いてあるか？
    // メモリレイアウトは？ アライメント要件は？
    
    let result = c_library_process(ptr);
    c_library_free(ptr);
    Ok(result)
}
```

このコードは「コンパイルが通る」ため、一見問題がないように見えます。ですが、実際には以下のリスクが潜んでいます：

- `c_library_allocate` が内部で別のメモリ管理手法を使っている
- `c_library_process` がポインタを別スレッドに渡す
- `c_library_free` の呼び出しタイミングがドキュメントと異なる実装になっている
- アライメント要件が満たされていない

Rustのコンパイラはこれらを **検出しません**。実行時に、ときに数時間後に、メモリ破壊として現れます。

## 検証の前提：外部ライブラリの「契約」を理解する

FFIを安全に使うには、まず外部ライブラリの振る舞いを正確に把握する必要があります。これは技術的な検証というより、**ドキュメント読解と仮説検証**です。

確認すべきポイント：

- メモリ所有権の明確化：誰がメモリを確保し、誰が解放するか
- スレッド安全性：複数スレッドからの同時呼び出しは可能か
- エラーハンドリング：失敗時の状態はどうなるか（特にポインタ）
- リソースリーク：ライブラリ内部で確保したリソースはどう管理するか
- 副作用：グローバル状態の変更、ファイルI/O、ネットワークアクセスがあるか

実装に入る前に、小さなテストプログラムでこれらを確認します。

```rust
#[cfg(test)]
mod ffi_contract_tests {
    use super::*;

    #[test]
    fn test_null_pointer_handling() {
        unsafe {
            let result = c_library_process(std::ptr::null_mut());
            // ヌルポインタでクラッシュするか、エラーを返すか、黙って進むか
            // ドキュメントと実装が一致しているか確認
            assert!(!result.is_null() || result.is_null()); // 予期した動作か
        }
    }

    #[test]
    fn test_memory_lifecycle() {
        unsafe {
            let ptr = c_library_allocate(1024);
            assert!(!ptr.is_null());
            
            // 同じポインタを複数回処理できるか
            c_library_process(ptr);
            c_library_process(ptr);
            
            // 解放後にアクセスしたらどうなるか（UBの検出）
            c_library_free(ptr);
            // ここでアクセスしてはいけないが、
            // メモリサニタイザーがないと気づかない
        }
    }
}
```

このテストは「パス・フェイル」ではなく、**ライブラリの実際の振る舞いを記録する** ためのものです。ドキュメントと実装の齟齬を早期に発見します。

## 監視と検証：Valgrind、AddressSanitizer、Miriの使い分け

メモリ破壊は静的には検出できないため、実行時の監視が必須です。ただし、ツールごとに得意な領域が異なります。

**AddressSanitizer（ASan）** は、ヒープバッファオーバーフロー、use-after-free、メモリリークを高速に検出します。Rustのテストと組み合わせやすいです：

```bash
RUSTFLAGS="-Zsanitizer=address" cargo +nightly test --target x86_64-unknown-linux-gnu
```

**Valgrind** はより詳細なメモリ追跡が可能ですが、オーバーヘッドが大きく、開発環境専用です。特にマルチスレッド環境での挙動確認に向いています。

**Miri** はRustの未定義動作（undefined behavior）を検出しますが、FFI呼び出しそのものは検査できません。unsafe ブロック内のRustコードの正当性確認に有効です。

実務では、この3つを段階的に使います：

1. **開発時**：AddressSanitizer で日常的に実行
2. **統合テスト**：Valgrind で詳細なメモリプロファイリング
3. **本番前**：複数の環境（Linux、macOS、異なるアーキテクチャ）で長時間の負荷テスト

## 設計判断：wrapper層を厚くする理由

FFIを使うコードは、往々にして「薄いwrapper」に留まります。しかし現場では、ここに投資することが後の保守性を大きく左右します。

具体的には：

- **所有権を明確にするRust型を定義する**：ポインタをそのまま扱わず、`struct` でラップし、`Drop` を実装して確実に解放する
- **入出力の検証層を挟む**：C側から返ってきた値が期待範囲内か、毎回確認する
- **エラーハンドリングを統一する**：C側のエラーコードをRustの `Result` に変換し、呼び出し側が統一的に扱える形にする

例えば：

```rust
pub struct CLibraryHandle {
    ptr: *mut c_void,
}

impl CLibraryHandle {
    pub fn new(size: usize) -> Result<Self, String> {
        unsafe {
            let ptr = c_library_allocate(size as u32);
            if ptr.is_null() {
                return Err("Allocation failed".to_string());
            }
            Ok(CLibraryHandle { ptr })
        }
    }

    pub fn process(&mut self, data: &[u8]) -> Result<Vec<u8>, String> {
        if data.is_empty() {
            return Err("Empty input".to_string());
        }
        
        unsafe {
            let result = c_library_process(self.ptr);
            if result.is_null() {
                return Err("Processing failed".to_string());
            }
            // 結果をRust側にコピー
            Ok(/* ... */)
        }
    }
}

impl Drop for CLibraryHandle {
    fn drop(&mut self) {
        unsafe {
            c_library_free(self.ptr);
        }
    }
}
```

このアプローチにより、unsafe の範囲が限定され、検証ポイントが明確になります。

## 本番投入前の確認チェックリスト

FFIを含むシステムを本番に出す前に、以下を確認します：

- [ ] 外部ライブラリのドキュメントを読み込み、メモリ管理の「契約」を明文化したか
- [ ] AddressSanitizer で少なくとも1週間のテストを実行し、メモリ警告がゼロか
- [ ] マルチスレッド環境での動作確認をしたか（Valgrind で Thread Sanitizer）
- [ ] エラーケース（メモリ不足、ライブラリの異常終了など）をシミュレートしたか
- [ ] 長時間の負荷テスト（24時間以上）でメモリリークがないか確認したか
- [ ] 複数バージョンの外部ライブラリで動作確認したか

特に最後の項目は見落とされやすいです。ライブラリのマイナーバージョン違いで、内部実装が変わることがあります。

## 誰に向いているか、どんな案件で採用しやすいか

Rustのパフォーマンスと安全性は魅力的ですが、FFIが必要な案件では、その利点が相殺されることがあります。

**FFI活用が現実的な案件**：
- 既に安定した、広く使われているC言語ライブラリ（OpenSSL、zlib など）を呼ぶ
- ライブラリのドキュメントが充実している
- メモリ管理の契約が明確で、テストケースが豊富に存在する
- チーム内に C言語経験者がいる

**避けるべき案件**：
- ドキュメントが不十分なレガシーライブラリ
- メモリ管理の仕様が曖昧
- 急なスケジュール（検証に時間をかけられない）

現場では、「Rustで書き直したい」という要望と「既存ライブラリを使わないといけない」という制約がぶつかることが多いです。その場合、FFIの検証コストを見積もった上で、本当にRustが最適か判断することが重要です。
