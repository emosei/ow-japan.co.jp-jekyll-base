"""
OpenWorks ブログ記事自動生成スクリプト
Claude API を使って技術記事を生成し、Jekyll の _posts/ に保存する
"""

import anthropic
import datetime
import os
import random
import re
import unicodedata


# ── テーマ定義 ──────────────────────────────────────────────

TECH_TIPS = [
    # モバイルアプリ開発
    "React Native と Flutter の最新比較：2024年はどちらを選ぶべきか",
    "iOSアプリのパフォーマンス改善で押さえておくべき5つのポイント",
    "Androidアプリ開発でよくある落とし穴と回避策",
    "モバイルアプリのオフライン対応設計パターン",
    "プッシュ通知の設計：ユーザー体験を損なわない実装方法",
    "モバイルアプリのCI/CD環境を整備する：Fastlane入門",
    "SwiftUI vs UIKit：既存プロジェクトへの段階的な移行戦略",
    "Jetpack Composeで変わるAndroid UI開発の現場",
    # Web開発
    "Next.js App Router 移行で学んだこと",
    "TypeScriptの型安全を最大限に活用するためのテクニック集",
    "Webアプリのパフォーマンス計測と改善：Core Web Vitals実践ガイド",
    "バックエンドAPI設計のベストプラクティス：REST vs GraphQL vs tRPC",
    "Docker Composeで整える快適なローカル開発環境",
    "フロントエンドテスト戦略：何をどこまでテストするか",
    "SQLクエリのパフォーマンスチューニング入門",
    "WebSocketとServer-Sent Eventsの使い分け",
    # システム開発共通
    "コードレビューを文化として根付かせるための取り組み",
    "小規模チームでも実践できるアジャイル開発のエッセンス",
    "技術的負債と向き合う：リファクタリング計画の立て方",
    "API認証の選択肢：JWT・OAuth2・セッション管理を整理する",
]

TECH_VERIFICATION = [
    "SwiftUIで簡単なToDoアプリを作ってみた",
    "Flutter 3.xの新機能を実際に試してみた",
    "React Native ExpoとBare Workflowを比較検証",
    "Next.js 15のTurbopackを本番環境で試した結果",
    "GitHub Copilotは実際に開発速度を上げるのか検証してみた",
    "Supabaseをバックエンドとして使ってみた感想",
    "PrismaとDrizzle ORMを実プロジェクトで比較",
    "Docker Composeで本番に近い開発環境を構築する",
    "Cloudflare WorkersでAPIを作って速度検証",
    "Vitestに移行して感じたJestとの違い",
    "SQLiteをモバイルアプリのローカルDBとして使う実装例",
    "Jetpack ComposeでカスタムUIコンポーネントを作ってみた",
    "XcodeのInstrumentsでiOSアプリのメモリリークを発見する手順",
    "PlaywrightでE2Eテストを書いてみた",
    "GitHub Actionsで自動デプロイ環境を整備した話",
]

IT_TRENDS = [
    "2024年注目のフロントエンドフレームワーク動向まとめ",
    "生成AIをアプリ開発に組み込む：実践的なアプローチ",
    "エッジコンピューティングがWebアプリ開発に与える影響",
    "WebAssemblyの現在地：どんなユースケースで使うべきか",
    "クラウドネイティブ開発の最新トレンド：KubernetesとServerlessの進化",
    "ローコード・ノーコードツールとプロ開発者の共存",
    "サイバーセキュリティの最新脅威と中小企業が取るべき対策",
    "開発者体験（DX）向上が注目される背景とツール動向",
    "AIコーディングアシスタントの現実：GitHub Copilotを使って感じたこと",
    "マイクロサービスとモノリス：2024年の現実的な選択",
    "Progressive Web Appの再評価：ネイティブアプリとの棲み分け",
    "SQLiteのルネッサンス：サーバーレスとエッジでの活躍",
    "プラットフォームエンジニアリングとは何か：DevOpsの次のステップ",
    "Rustがシステム開発にもたらす変化",
    "量子コンピューティングがソフトウェア開発者に関係する理由",
]

CATEGORIES = {
    "tech-tips": {
        "topics": TECH_TIPS,
        "category": "tech-tips",
        "category_ja": "技術Tips",
    },
    "it-trends": {
        "topics": IT_TRENDS,
        "category": "it-trends",
        "category_ja": "ITトレンド",
    },
    "tech-verification": {
        "topics": TECH_VERIFICATION,
        "category": "tech-verification",
        "category_ja": "技術検証",
    },
}


# ── プロンプト生成 ─────────────────────────────────────────

def build_prompt(topic: str, category_ja: str) -> str:
    return f"""あなたはシステム開発会社「有限会社OpenWorks」のテックブログ執筆者です。
以下のテーマで、エンジニアや技術に興味のあるビジネスパーソン向けの記事を日本語で書いてください。

テーマ: {topic}
カテゴリ: {category_ja}

【要件】
- 文字数: 800〜1200字程度
- 読者: Webエンジニア、モバイルエンジニア、IT担当者
- トーン: 実務的・わかりやすい・親しみやすい（です・ます調）
- 構成: 導入 → 本文（見出し2〜4つ） → まとめ
- Markdown形式で書く（見出しは ## と ### を使用）
- コードブロックがあれば ```言語名 で囲む
- 最後に3〜5個のタグをカンマ区切りで「タグ: tag1, tag2, tag3」の形式で1行追記する

記事本文のみ出力してください（前置き・後書き不要）。
"""


# ── ファイル名用スラッグ生成 ───────────────────────────────

def slugify(text: str) -> str:
    """日本語タイトルを英数字スラッグに変換（簡易版）"""
    # ASCII以外を除去してハイフン繋ぎにする
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.ASCII)
    text = re.sub(r"[\s_]+", "-", text).strip("-").lower()
    return text or "post"


def make_filename(date: datetime.date, title_hint: str) -> str:
    slug = slugify(title_hint)[:50] or "blog-post"
    return f"_posts/{date.strftime('%Y-%m-%d')}-{slug}.md"


# ── タグ抽出 ──────────────────────────────────────────────

def extract_tags(body: str) -> tuple[str, list[str]]:
    """本文末尾の「タグ: ...」行を取り出してリストで返す"""
    lines = body.strip().splitlines()
    tags: list[str] = []
    clean_lines = []
    for line in lines:
        m = re.match(r"^タグ[:：]\s*(.+)$", line.strip())
        if m:
            tags = [t.strip() for t in m.group(1).split(",") if t.strip()]
        else:
            clean_lines.append(line)
    return "\n".join(clean_lines).strip(), tags


# ── Jekyll フロントマター生成 ──────────────────────────────

def build_frontmatter(title: str, date: datetime.date, category: str, tags: list[str]) -> str:
    tag_str = ", ".join(f'"{t}"' for t in tags)
    return f"""---
layout: post
title: "{title}"
date: {date.strftime('%Y-%m-%d')}
categories: {category}
tags: [{tag_str}]
author: OpenWorks
---
"""


# ── メイン ────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません")

    # 自由テーマが指定されていればそれを使う
    free_topic = os.environ.get("TOPIC", "").strip()
    category_key = os.environ.get("CATEGORY", "random").lower()
    if free_topic:
        topic = free_topic
        # 自由テーマでもカテゴリ指定があればそれを使う
        if category_key in CATEGORIES:
            config = CATEGORIES[category_key]
        else:
            config = CATEGORIES["tech-verification"]
        print(f"自由テーマ: {topic}")
    else:
        # カテゴリから自動選択
        category_key = os.environ.get("CATEGORY", "random").lower()
        if category_key not in CATEGORIES:
            category_key = random.choice(list(CATEGORIES.keys()))
        config = CATEGORIES[category_key]
        topic = random.choice(config["topics"])
        print(f"カテゴリ: {config['category_ja']}")
        print(f"テーマ: {topic}")

    # Claude API で記事生成
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[
            {"role": "user", "content": build_prompt(topic, config["category_ja"])}
        ],
    )
    raw_body = message.content[0].text

    # タグ抽出
    body, tags = extract_tags(raw_body)

    # ファイル保存
    today = datetime.date.today()
    filename = make_filename(today, topic)
    frontmatter = build_frontmatter(topic, today, config["category"], tags)
    content = frontmatter + "\n" + body + "\n"

    os.makedirs("_posts", exist_ok=True)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"✅ 保存しました: {filename}")
    print(f"   タグ: {tags}")


if __name__ == "__main__":
    main()
