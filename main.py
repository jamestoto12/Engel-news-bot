"""
법무부 출입국·외국인정책본부 언론대응 뉴스봇
- AI 없이 운영 (중복제거 + 키워드 필터만)
"""

import os
import json
import hashlib
from datetime import datetime, date
from news_collector import NewsCollector
from telegram_sender import TelegramSender
from response_formatter import ResponseFormatter
from google_rss_collector import GoogleRSSCollector

# ── 관심 키워드 ──────────────────────────────────────────────────
KEYWORDS = [
    "계절근로자",
    "외국인 선원",
    "어선 외국인",
    "수산 외국인",
    "해수부 외국인",
    "어선 사고",
    "외국인력 수산",
]

# ── 제목에 반드시 포함돼야 할 키워드 (제목 필터) ─────────────────
# 아래 중 하나라도 제목에 있어야 전송
TITLE_MUST_INCLUDE = [
    "외국인", "계절근로", "어선원", "선원", "이민", "출입국",
    "비자", "E-8", "E-9", "E-10", "불법체류", "외국인력",
    "수산 인력", "어업 인력",
]

HISTORY_FILE = "sent_history.json"


def load_history() -> set:
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("hashes", []))
    return set()


def save_history(hashes: set):
    hash_list = list(hashes)[-500:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"hashes": hash_list, "updated": str(date.today())}, f, ensure_ascii=False, indent=2)


def make_hash(article: dict) -> str:
    key = article.get("title", "") + article.get("link", "")
    return hashlib.md5(key.encode()).hexdigest()


def title_filter(title: str) -> bool:
    """제목에 핵심 키워드가 하나라도 있어야 통과"""
    return any(kw in title for kw in TITLE_MUST_INCLUDE)


def dedup(articles: list) -> list:
    """URL + 제목 앞 10자 기준 중복 제거"""
    seen_links = set()
    seen_titles = set()
    result = []
    for art in articles:
        link = art.get("link", "")
        title_key = art.get("title", "").strip()[:10]
        if link not in seen_links and title_key not in seen_titles:
            seen_links.add(link)
            seen_titles.add(title_key)
            result.append(art)
    return result


def main():
    print(f"\n{'='*60}")
    print(f"뉴스봇 실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    naver_client_id = os.environ.get("NAVER_CLIENT_ID")
    naver_client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    collector = NewsCollector(naver_client_id, naver_client_secret)
    rss_collector = GoogleRSSCollector()
    sender = TelegramSender(telegram_token, telegram_chat_id)
    formatter = ResponseFormatter()

    sent_hashes = load_history()

    # ── 1단계: 수집 ──────────────────────────────────────────────
    all_articles = []
    for keyword in KEYWORDS:
        naver = collector.search(keyword, display=10)
        google = rss_collector.search(keyword, days=3)
        all_articles.extend(naver)
        all_articles.extend(google)
        print(f"  [{keyword}] 네이버:{len(naver)} + 구글:{len(google)}")

    print(f"\n총 수집: {len(all_articles)}건")

    # ── 2단계: 중복 제거 (URL + 제목 앞 10자) ────────────────────
    unique = dedup(all_articles)
    print(f"중복 제거 후: {len(unique)}건")

    # ── 3단계: 제목 키워드 필터 ──────────────────────────────────
    filtered = [a for a in unique if title_filter(a.get("title", ""))]
    print(f"제목 필터 후: {len(filtered)}건")

    # ── 4단계: 이미 전송한 기사 제외 ────────────────────────────
    new_articles = [a for a in filtered if make_hash(a) not in sent_hashes]
    print(f"신규 기사: {len(new_articles)}건\n")

    if not new_articles:
        sender.send_message("📭 [뉴스봇] 신규 관련 기사가 없습니다.")
        return

    # ── 5단계: 전송 (하나의 메시지로 합쳐서) ────────────────────
    today_str = date.today().strftime("%Y년 %m월 %d일")
    
    # 헤더 + 모든 기사 합치기
    parts = [f"📰 {today_str} 언론동향 브리핑"]
    parts.append(f"법무부 출입국·외국인정책본부")
    parts.append(f"총 {len(new_articles)}건 | {datetime.now().strftime('%H:%M')}")
    parts.append("━" * 30)
    parts.append("")

    new_hashes = set()
    for i, article in enumerate(new_articles, 1):
        msg = formatter.format_response(article, index=i)
        parts.append(msg)
        parts.append("")  # 기사 사이 빈줄
        new_hashes.add(make_hash(article))
        print(f"  포함: {article.get('title','')[:40]}...")

    # 하나의 메시지로 전송 (텔레그램이 길면 자동 분할)
    full_message = "\n".join(parts)
    sender.send_message(full_message)

    sent_hashes.update(new_hashes)
    save_history(sent_hashes)

    print(f"\n완료: {len(new_articles)}건")


if __name__ == "__main__":
    main()
