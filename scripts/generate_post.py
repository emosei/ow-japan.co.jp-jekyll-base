"""
OpenWorks ブログ記事自動生成スクリプト
Claude API を使って技術記事を生成し、Jekyll の _posts/ に保存する
"""

from __future__ import annotations

import datetime
import json
import os
import random
import re
import unicodedata
from pathlib import Path

import anthropic


# ── カテゴリごとの発想キーワード ────────────────────────────

TECH_TIPS = [
    "モバイル開発",
    "Ruby",
    "基幹システム",
    "アジャイル",
    "アーキテクチャ",
]

TECH_VERIFICATION = [
    "関数型言語",
    "Ruby",
    "Haskell",
    "Rust",
    "Go",
    "JavaScript",
    "認証",
    "Webサーバー",
    "Webアプリミドルウェア",
]

IT_TRENDS: list[str] = []

CATEGORIES = {
    "tech-tips": {
        "keywords": TECH_TIPS,
        "category": "tech-tips",
        "category_ja": "技術Tips",
        "topic_guidance": "実務で使える設計・改善・運用ノウハウに寄せる",
        "focus_keyword_count": 1,
    },
    "it-trends": {
        "keywords": IT_TRENDS,
        "category": "it-trends",
        "category_ja": "ITトレンド",
        "topic_guidance": "開発現場や事業運営に影響する変化を、実務目線で整理する",
        "focus_keyword_count": 0,
    },
    "tech-verification": {
        "keywords": TECH_VERIFICATION,
        "category": "tech-verification",
        "category_ja": "技術検証",
        "topic_guidance": "試す・比較する・検証する切り口で、再現性のあるテーマに寄せる",
        "focus_keyword_count": 1,
    },
}

POSTS_DIR = Path("_posts")
MAX_RELATED_POSTS = 3
MAX_RECENT_POST_CONTEXT = 20
MAX_GENERATION_ATTEMPTS = 2
TOPIC_CANDIDATE_COUNT = 10
TOPIC_SELECTION_POOL = 4
TOPIC_DUPLICATE_THRESHOLD = 0.72
TITLE_DUPLICATE_THRESHOLD = 0.86
BODY_DUPLICATE_THRESHOLD = 0.82
MODEL_NAME = "claude-haiku-4-5-20251001"

PROMPT_PROFILES = {
    "tech-tips": {
        "length": "2200〜3200字程度",
        "sections": "4〜6個",
        "must_cover": [
            "現場でそのテーマが問題になる背景と、見落とされやすい課題",
            "設計や技術選定で判断すべきポイントとトレードオフ",
            "実装・設定・運用の具体例を1つ以上。コードや設定値は省略しすぎない",
            "導入時や運用時にハマりやすい落とし穴と回避策",
            "小規模チームでも始めやすい現実的な導入ステップ",
        ],
        "extra_rules": [
            "抽象論で終わらせず、読者が実務でそのまま判断材料に使える密度で書く",
            "必要に応じてコードブロックや設定ファイル例を入れる",
            "『どう使うか』だけでなく『どういう条件では向かないか』も書く",
        ],
    },
    "tech-verification": {
        "length": "2400〜3400字程度",
        "sections": "4〜6個",
        "must_cover": [
            "検証の目的、前提条件、比較観点",
            "検証手順や構成を再現できるレベルの具体性",
            "試して分かった利点・制約・注意点",
            "実務投入するなら追加で確認すべきポイント",
            "誰に向いているか、どんな案件で採用しやすいか",
        ],
        "extra_rules": [
            "感想だけで終わらせず、検証の観点と結果を切り分けて書く",
            "実験条件やサンプル構成が想像できる程度に具体化する",
            "コード例・設定例・コマンド例のうち最低1つは含める",
        ],
    },
    "it-trends": {
        "length": "1800〜2600字程度",
        "sections": "3〜5個",
        "must_cover": [
            "トレンドが注目される背景",
            "開発現場への具体的な影響",
            "導入が向くケースと向かないケース",
            "中小規模の開発組織が現実的に取れるアクション",
        ],
        "extra_rules": [
            "流行の紹介だけで終わらせず、実務での含意まで落とし込む",
            "過度に煽らず、現実的なメリットと制約を併記する",
        ],
    },
}

AUTHOR_PERSONA = {
    "identity": [
        "小規模なIT企業を起業して経営している人物だが、その立場を過剰にアピールしない",
        "40代後半のベテランエンジニアで、現場で叩き上げられてきた技術者",
        "独学ベースでコンピュータサイエンスを学んできた",
        "限られた顧客から継続的に仕事を得ており、信頼関係の中で案件を任されている",
    ],
    "experience": [
        "基幹系では大手旅行会社向けシステムを複数担当してきた",
        "例として、ANAスカイホリデーの予約システム、日本旅行の予約システム、近畿日本ツーリストの予約管理システム、JRえきねっとの販売店システムに関わってきた",
        "加えて、GDOスコアのモバイルアプリ、IODataのデバイス向けアプリ、お弁当宅配サービス、商店街向けホームページおよびアプリ、デジタルコンテンツ販売サイト構築なども経験している",
    ],
    "voice": [
        "人を頭ごなしに否定せず、穏やかで優しい語り口",
        "ただし技術や設計の甘さには厳しく、論点は鋭く切り分ける",
        "理論の引用だけでなく、現場で起きる問題、運用、保守、制約まで踏まえて語る",
    ],
    "rules": [
        "記事本文では毎回自己紹介しない",
        "携わった企業名、サービス名、団体名を本文中に出さない。固有名詞の実績紹介は禁止する",
        "顧客名や実績を並べて権威づけしない。必要なら経験に裏打ちされた視点として自然ににじませる",
        "経験談や実体験を語る場合も、案件を特定できる具体的な描写、時期、規模、固有の経緯は書かない",
        "経験に触れる場合は『現場ではこういう判断が起きやすい』のように一般化し、作り込んだ逸話にしない",
        "上から目線にせず、実務の難しさに敬意を払う",
    ],
}


# ── 類似度計算と既存記事読み込み ────────────────────────────

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^\wぁ-んァ-ヶ一-龠ー]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def char_ngrams(text: str, n: int = 2) -> set[str]:
    compact = normalize_text(text).replace(" ", "")
    if not compact:
        return set()
    if len(compact) <= n:
        return {compact}
    return {compact[index : index + n] for index in range(len(compact) - n + 1)}


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def text_similarity(left: str, right: str, n: int = 2) -> float:
    left_normalized = normalize_text(left)
    right_normalized = normalize_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    if left_normalized == right_normalized:
        return 1.0

    score = jaccard_similarity(char_ngrams(left_normalized, n=n), char_ngrams(right_normalized, n=n))
    if len(left_normalized) >= 6 and len(right_normalized) >= 6:
        if left_normalized in right_normalized or right_normalized in left_normalized:
            score = max(score, 0.88)
    return score


def parse_tags(raw_tags: str) -> list[str]:
    if not raw_tags:
        return []

    quoted_tags = re.findall(r'"([^"]+)"', raw_tags)
    if quoted_tags:
        return quoted_tags

    cleaned = raw_tags.strip().strip("[]")
    if not cleaned:
        return []

    return [tag.strip().strip('"').strip("'") for tag in cleaned.split(",") if tag.strip()]


def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content

    metadata: dict[str, str] = {}
    body_start = 0
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = index + 1
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()

    body = "\n".join(lines[body_start:]).strip()
    return metadata, body


def load_existing_posts() -> list[dict[str, object]]:
    posts: list[dict[str, object]] = []
    if not POSTS_DIR.exists():
        return posts

    for path in sorted(POSTS_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(content)
        posts.append(
            {
                "path": path,
                "title": metadata.get("title", "").strip().strip('"'),
                "category": metadata.get("categories", "").strip(),
                "date": metadata.get("date", "").strip() or path.stem[:10],
                "tags": parse_tags(metadata.get("tags", "")),
                "body": body,
            }
        )

    return posts


def sort_posts_by_recency(existing_posts: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(existing_posts, key=lambda post: str(post["date"]), reverse=True)


def find_latest_category_for_date(existing_posts: list[dict[str, object]], target_date: datetime.date) -> str | None:
    target_date_str = target_date.isoformat()
    for post in sort_posts_by_recency(existing_posts):
        if str(post["date"]) != target_date_str:
            continue
        category = str(post["category"]).strip()
        if category:
            return category
    return None


def choose_category_key(
    requested_category: str,
    existing_posts: list[dict[str, object]],
    today: datetime.date,
) -> str:
    if requested_category in CATEGORIES:
        return requested_category

    available_categories = list(CATEGORIES.keys())
    latest_category_today = find_latest_category_for_date(existing_posts, today)

    if latest_category_today in available_categories and len(available_categories) > 1:
        filtered_categories = [category for category in available_categories if category != latest_category_today]
        if filtered_categories:
            print(f"本日の直前カテゴリを回避: {latest_category_today}")
            return random.choice(filtered_categories)

    return random.choice(available_categories)


def find_related_posts(topic: str, existing_posts: list[dict[str, object]], limit: int = MAX_RELATED_POSTS) -> list[dict[str, object]]:
    related_posts: list[dict[str, object]] = []
    for post in existing_posts:
        title_score = text_similarity(topic, str(post["title"]))
        tag_score = max((text_similarity(topic, tag) for tag in post["tags"]), default=0.0)
        score = max(title_score, tag_score)
        if score <= 0:
            continue
        related_posts.append(
            {
                "post": post,
                "score": score,
                "title_score": title_score,
                "tag_score": tag_score,
            }
        )

    related_posts.sort(key=lambda item: item["score"], reverse=True)
    return related_posts[:limit]


def choose_topic(topic_candidates: list[str], existing_posts: list[dict[str, object]]) -> tuple[str, list[dict[str, object]]]:
    if not topic_candidates:
        raise RuntimeError("テーマ候補を生成できませんでした")

    ranked_candidates: list[tuple[float, float, str, list[dict[str, object]]]] = []
    for topic in topic_candidates:
        related_posts = find_related_posts(topic, existing_posts)
        strongest_match = related_posts[0]["score"] if related_posts else 0.0
        total_overlap = sum(item["score"] for item in related_posts)
        ranked_candidates.append((strongest_match, total_overlap, topic, related_posts))

    ranked_candidates.sort(key=lambda item: (item[0], item[1]))
    fresh_candidates = [item for item in ranked_candidates if item[0] < TOPIC_DUPLICATE_THRESHOLD]
    selection_pool = fresh_candidates or ranked_candidates
    selection_width = min(TOPIC_SELECTION_POOL, len(selection_pool))
    strongest_match, _, topic, related_posts = random.choice(selection_pool[:selection_width])

    if strongest_match >= TOPIC_DUPLICATE_THRESHOLD:
        print("⚠️ 近いテーマが多いため、既存記事との差分を意識して生成します")

    return topic, related_posts


def format_related_posts(related_posts: list[dict[str, object]]) -> str:
    if not related_posts:
        return "- 関連する過去記事は見つかりませんでした"

    lines = []
    for item in related_posts[:MAX_RELATED_POSTS]:
        post = item["post"]
        tags = ", ".join(post["tags"][:4]) if post["tags"] else "タグなし"
        lines.append(
            f"- 「{post['title']}」 ({post['date']} / {post['category']} / タグ: {tags})"
        )
    return "\n".join(lines)


def format_recent_posts(existing_posts: list[dict[str, object]], limit: int = MAX_RECENT_POST_CONTEXT) -> str:
    recent_posts = sort_posts_by_recency(existing_posts)[:limit]
    if not recent_posts:
        return "- 過去記事はまだありません"

    lines = []
    for post in recent_posts:
        lines.append(f"- {post['date']}: 「{post['title']}」 ({post['category']})")
    return "\n".join(lines)


def render_similarity_hint(related_posts: list[dict[str, object]]) -> str:
    if not related_posts:
        return "なし"
    return " / ".join(f"「{item['post']['title']}」" for item in related_posts)


def choose_focus_keywords(keywords: list[str], count: int) -> list[str]:
    if not keywords or count <= 0:
        return []
    if len(keywords) <= count:
        return keywords[:]
    return random.sample(keywords, count)


def format_author_persona() -> str:
    identity = "\n".join(f"- {item}" for item in AUTHOR_PERSONA["identity"])
    experience = "\n".join(f"- {item}" for item in AUTHOR_PERSONA["experience"])
    voice = "\n".join(f"- {item}" for item in AUTHOR_PERSONA["voice"])
    rules = "\n".join(f"- {item}" for item in AUTHOR_PERSONA["rules"])
    return f"""【書き手のペルソナ】
人物像:
{identity}

経験領域:
{experience}

文体と視点:
{voice}

扱い方のルール:
{rules}
"""


# ── テーマ候補生成 ────────────────────────────────────────

def build_topic_ideation_prompt(
    category_key: str,
    category_ja: str,
    topic_guidance: str,
    category_keywords: list[str],
    focus_keywords: list[str],
    existing_posts: list[dict[str, object]],
) -> str:
    current_year = datetime.date.today().year
    keyword_pool = " / ".join(category_keywords) if category_keywords else "特になし"
    focus_text = " / ".join(focus_keywords) if focus_keywords else "特になし"

    if focus_keywords:
        keyword_rules = f"""
【今回の発想キーワード】
- カテゴリ全体のキーワード: {keyword_pool}
- 今回は特に「{focus_text}」を軸に考える
- ただしキーワードをそのままタイトルに置くだけでなく、具体的な課題や判断ポイントに落とし込む
"""
    else:
        keyword_rules = """
【今回の発想キーワード】
- 特定のキーワードは設けない
- 受託開発や自社サービス開発の現場で、実務に影響するITトレンドを優先する
"""

    return f"""あなたはシステム開発会社「有限会社OpenWorks」の編集者です。
テックブログ用に、新しい記事テーマ案だけを考えてください。

{format_author_persona()}

カテゴリ: {category_ja}
カテゴリの方向性: {topic_guidance}

【最近の投稿】
{format_recent_posts(existing_posts)}

{keyword_rules}

【テーマ案の条件】
- 日本語の具体的な記事タイトルとして成立すること
- 過去記事と同じ主題や、ほぼ同じ切り口を避けること
- 似た案を並べず、観点をばらけさせること
- 古い年号に依存しないこと。年号を入れるなら {current_year} 年以外を使わない
- 「最新まとめ」「入門」だけの抽象的なタイトルは避ける
- 実務で深掘りしやすい、論点のあるタイトルにする
- カテゴリの性格を守ること
  - tech-tips: 実務ノウハウや設計・改善の勘所
  - tech-verification: 何かを試す、比較する、検証する
  - it-trends: 変化の背景と実務への影響

{TOPIC_CANDIDATE_COUNT}個の候補を出してください。

【出力形式】
JSON配列のみを返してください。
例:
["候補1", "候補2"]
"""


def clean_topic_candidate(candidate: str) -> str:
    cleaned = str(candidate).strip()
    cleaned = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", cleaned)
    cleaned = re.sub(r"^(?:タイトル|title)[:：]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip().strip('"').strip("'")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def deduplicate_topic_candidates(topic_candidates: list[str]) -> list[str]:
    deduped: list[str] = []
    for candidate in topic_candidates:
        cleaned = clean_topic_candidate(candidate)
        if len(cleaned) < 8:
            continue
        if any(text_similarity(cleaned, existing) >= 0.85 for existing in deduped):
            continue
        deduped.append(cleaned)
    return deduped


def parse_topic_candidates(raw_text: str) -> list[str]:
    stripped = raw_text.strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start != -1 and end != -1 and end > start:
        json_block = stripped[start : end + 1]
        try:
            data = json.loads(json_block)
            if isinstance(data, list):
                return deduplicate_topic_candidates([str(item) for item in data])
        except json.JSONDecodeError:
            pass

    candidates: list[str] = []
    for line in stripped.splitlines():
        cleaned = clean_topic_candidate(line)
        if cleaned:
            candidates.append(cleaned)
    return deduplicate_topic_candidates(candidates)


def generate_topic_candidates(
    client: anthropic.Anthropic,
    category_key: str,
    category_ja: str,
    topic_guidance: str,
    category_keywords: list[str],
    focus_keywords: list[str],
    existing_posts: list[dict[str, object]],
) -> list[str]:
    prompt = build_topic_ideation_prompt(
        category_key=category_key,
        category_ja=category_ja,
        topic_guidance=topic_guidance,
        category_keywords=category_keywords,
        focus_keywords=focus_keywords,
        existing_posts=existing_posts,
    )
    message = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1400,
        temperature=0.9,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = extract_text_blocks(message)
    candidates = parse_topic_candidates(raw_text)
    if not candidates:
        raise RuntimeError("テーマ候補の生成に失敗しました")
    return candidates


# ── プロンプト生成 ─────────────────────────────────────────

def build_prompt(
    topic: str,
    category_key: str,
    category_ja: str,
    related_posts: list[dict[str, object]],
    attempt: int,
    focus_keywords: list[str],
) -> str:
    profile = PROMPT_PROFILES[category_key]
    must_cover = "\n".join(f"- {item}" for item in profile["must_cover"])
    extra_rules = "\n".join(f"- {item}" for item in profile["extra_rules"])

    keyword_block = ""
    if focus_keywords:
        keyword_block = f"""
【テーマ生成時に参照したキーワード】
- {" / ".join(focus_keywords)}
- 記事全体の論点が、上記キーワードと自然につながるようにする
"""

    retry_note = ""
    if attempt > 1:
        retry_note = """
【再生成時の追加指示】
- 直前の生成結果は過去記事との切り口が近すぎました。
- より具体的なユースケース、別の比較軸、別の失敗パターンに寄せて書き直してください。
- タイトル・導入・見出し順・コード例が過去記事と似ないようにしてください。
"""

    return f"""あなたはシステム開発会社「有限会社OpenWorks」のテックブログ執筆者です。
エンジニアやIT担当者が読んで「現場で使える」「判断材料になる」と感じる、日本語の実務寄りブログ記事を書いてください。

{format_author_persona()}

テーマ: {topic}
カテゴリ: {category_ja}
{keyword_block}

【近い過去記事】
{format_related_posts(related_posts)}

【重複回避ルール】
- 過去記事と同じタイトルにしない
- 同じ導入、同じ見出し構成、同じコード例を繰り返さない
- 近いテーマの場合は、より具体的なサブテーマ・別の比較軸・別の失敗例・別の設計判断に絞る
- 過去記事で触れていない論点を中心に、追加価値がある内容にする
{retry_note}

【出力形式】
- 1行目は必ず `タイトル: ...`
- 本文はMarkdown形式で、H1は使わず `##` と `###` で構成する
- 最後の1行は必ず `タグ: tag1, tag2, tag3`
- 記事以外の前置き、補足説明、あとがきは出力しない

【共通要件】
- 文字数: {profile['length']}
- 読者: Webエンジニア、モバイルエンジニア、IT担当者
- トーン: 実務的・わかりやすい・親しみやすい（です・ます調）
- 見出し数: {profile['sections']}
- 導入は一般論で引き延ばさず、現場で起こる具体的な課題や判断場面から始める
- 説明は抽象論で終わらせず、設計判断・実装観点・運用上の注意まで踏み込む
- 必要に応じて箇条書きやコードブロックを使う
- コードブロックがあれば ```言語名 で囲む

【このカテゴリで必ず触れること】
{must_cover}

【追加ルール】
{extra_rules}
"""


# ── ファイル名用スラッグ生成 ───────────────────────────────

def slugify(text: str) -> str:
    """日本語タイトルを英数字スラッグに変換（簡易版）"""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.ASCII)
    text = re.sub(r"[\s_]+", "-", text).strip("-").lower()
    return text or "post"


def make_filename(date: datetime.date, title_hint: str) -> str:
    slug = slugify(title_hint)[:60] or "blog-post"
    candidate = POSTS_DIR / f"{date.strftime('%Y-%m-%d')}-{slug}.md"
    if not candidate.exists():
        return str(candidate)

    suffix = 2
    while True:
        alternative = POSTS_DIR / f"{date.strftime('%Y-%m-%d')}-{slug}-{suffix}.md"
        if not alternative.exists():
            return str(alternative)
        suffix += 1


# ── 生成結果の整形 ─────────────────────────────────────────

def sanitize_tags(tags: list[str]) -> list[str]:
    cleaned_tags: list[str] = []
    seen: set[str] = set()

    for tag in tags:
        normalized = re.sub(r"\s+", " ", tag).strip().strip('"').strip("'").strip("[]")
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_tags.append(normalized)

    return cleaned_tags[:5]


def extract_article_parts(raw_text: str, fallback_title: str) -> tuple[str, str, list[str]]:
    lines = raw_text.strip().splitlines()
    title = fallback_title
    tags: list[str] = []
    body_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        title_match = re.match(r"^(?:タイトル|title)[:：]\s*(.+)$", stripped, flags=re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip().strip('"')
            continue

        tag_match = re.match(r"^タグ[:：]\s*(.+)$", stripped)
        if tag_match:
            tags = [tag.strip() for tag in tag_match.group(1).split(",") if tag.strip()]
            continue

        body_lines.append(line)

    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)

    if body_lines:
        heading_match = re.match(r"^#\s+(.+)$", body_lines[0].strip())
        if heading_match and text_similarity(heading_match.group(1), title) >= 0.9:
            body_lines.pop(0)
            while body_lines and not body_lines[0].strip():
                body_lines.pop(0)

    body = "\n".join(body_lines).strip()
    return title or fallback_title, body, sanitize_tags(tags)


def find_duplicate_posts(title: str, body: str, existing_posts: list[dict[str, object]]) -> list[dict[str, object]]:
    duplicate_candidates: list[dict[str, object]] = []
    body_sample = body[:1600]

    for post in existing_posts:
        title_score = text_similarity(title, str(post["title"]))
        body_score = text_similarity(body_sample, str(post["body"])[:1600], n=3)
        score = max(title_score, body_score)
        if score <= 0:
            continue
        duplicate_candidates.append(
            {
                "post": post,
                "score": score,
                "title_score": title_score,
                "body_score": body_score,
            }
        )

    duplicate_candidates.sort(key=lambda item: item["score"], reverse=True)
    return duplicate_candidates[:MAX_RELATED_POSTS]


def should_retry_generation(duplicate_candidates: list[dict[str, object]]) -> bool:
    if not duplicate_candidates:
        return False

    best_match = duplicate_candidates[0]
    return (
        best_match["title_score"] >= TITLE_DUPLICATE_THRESHOLD
        or best_match["body_score"] >= BODY_DUPLICATE_THRESHOLD
    )


def extract_text_blocks(message: anthropic.types.Message) -> str:
    chunks = [block.text for block in message.content if getattr(block, "type", None) == "text"]
    return "\n".join(chunks).strip()


# ── Jekyll フロントマター生成 ──────────────────────────────

def escape_yaml_string(value: str) -> str:
    return value.replace('"', '\\"')


def build_frontmatter(title: str, date: datetime.date, category: str, tags: list[str]) -> str:
    escaped_title = escape_yaml_string(title)
    tag_str = ", ".join(f'"{escape_yaml_string(tag)}"' for tag in tags)
    return f"""---
layout: post
title: "{escaped_title}"
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

    today = datetime.date.today()
    existing_posts = load_existing_posts()
    print(f"既存記事数: {len(existing_posts)}")

    client = anthropic.Anthropic(api_key=api_key)
    focus_keywords: list[str] = []
    free_topic = os.environ.get("TOPIC", "").strip()
    category_key = os.environ.get("CATEGORY", "random").lower()
    if free_topic:
        topic = free_topic
        if category_key in CATEGORIES:
            config = CATEGORIES[category_key]
        else:
            config = CATEGORIES["tech-verification"]
        related_posts = find_related_posts(topic, existing_posts)
        print(f"自由テーマ: {topic}")
    else:
        category_key = choose_category_key(category_key, existing_posts, today)
        config = CATEGORIES[category_key]
        focus_keywords = choose_focus_keywords(
            config["keywords"],
            config["focus_keyword_count"],
        )
        topic_candidates = generate_topic_candidates(
            client=client,
            category_key=config["category"],
            category_ja=config["category_ja"],
            topic_guidance=config["topic_guidance"],
            category_keywords=config["keywords"],
            focus_keywords=focus_keywords,
            existing_posts=existing_posts,
        )
        topic, related_posts = choose_topic(topic_candidates, existing_posts)
        print(f"カテゴリ: {config['category_ja']}")
        if focus_keywords:
            print(f"発想キーワード: {' / '.join(focus_keywords)}")
        print(f"テーマ候補数: {len(topic_candidates)}")
        print(f"テーマ: {topic}")

    generated_title = topic
    body = ""
    tags: list[str] = []
    duplicate_candidates: list[dict[str, object]] = []

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        if related_posts:
            print(f"近い既存記事: {render_similarity_hint(related_posts)}")

        message = client.messages.create(
            model=MODEL_NAME,
            max_tokens=3200,
            temperature=0.7,
            messages=[
                {
                    "role": "user",
                    "content": build_prompt(
                        topic=topic,
                        category_key=config["category"],
                        category_ja=config["category_ja"],
                        related_posts=related_posts,
                        attempt=attempt,
                        focus_keywords=focus_keywords,
                    ),
                }
            ],
        )
        raw_text = extract_text_blocks(message)
        generated_title, body, tags = extract_article_parts(raw_text, topic)

        if not body:
            raise RuntimeError("記事本文の生成に失敗しました")

        duplicate_candidates = find_duplicate_posts(generated_title, body, existing_posts)
        if attempt < MAX_GENERATION_ATTEMPTS and should_retry_generation(duplicate_candidates):
            print(
                "⚠️ 過去記事との類似度が高いため再生成します: "
                f"{render_similarity_hint(duplicate_candidates)}"
            )
            related_posts = duplicate_candidates
            continue
        break

    if should_retry_generation(duplicate_candidates):
        print(
            "⚠️ 近い既存記事があります。公開前に内容確認を推奨します: "
            f"{render_similarity_hint(duplicate_candidates)}"
        )

    filename = make_filename(today, generated_title)
    frontmatter = build_frontmatter(generated_title, today, config["category"], tags)
    content = frontmatter + "\n" + body + "\n"

    os.makedirs(POSTS_DIR, exist_ok=True)
    with open(filename, "w", encoding="utf-8") as file:
        file.write(content)

    print(f"✅ 保存しました: {filename}")
    print(f"   タイトル: {generated_title}")
    print(f"   タグ: {tags}")


if __name__ == "__main__":
    main()
