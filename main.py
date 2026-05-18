"""
법무부 출입국·외국인정책본부 언론대응 뉴스봇
"""

import os
import json
import hashlib
from datetime import datetime, date
from news_collector import NewsCollector
from ai_summarizer import AISummarizer
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

# ── 제외 키워드 (AI 없이 바로 제거) ──────────────────────────────
EXCLUDE_KEYWORDS = [
    # 완전 무관
    "맛집", "요리", "레시피", "할인", "이벤트",
    "음식점", "셰프", "식당", "축제",
    # 선거/정치
    "선거", "3파전", "후보", "공천", "출마",
    # 재난/날씨 (외국인 무관)
    "이상고온", "태풍", "지진", "산불",
    # 복지/의료 (출입국 무관)
    "노약자", "복지관", "경로당", "요양",
    # 물류/건설
    "물류단지", "물류센터", "건설공사",
    # 소방/안전교육 단독
    "소방안전교육", "소방훈련",
    # 봉사
    "봉사활동", "자원봉사",
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


def is_excluded(title: str, description: str) -> bool:
    text = title + description
    return any(kw in text for kw in EXCLUDE_KEYWORDS)


def dedup_by_title(articles: list) -> list:
    """제목 앞 15자 기준 중복 제거"""
    seen_titles = set()
    seen_links = set()
    result = []
    for art in articles:
        link = art.get("link", "")
        title_key = art.get("title", "").strip()[:15]
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
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    collector = NewsCollector(naver_client_id, naver_client_secret)
    rss_collector = GoogleRSSCollector()
    summarizer = AISummarizer(gemini_api_key)
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

    # ── 2단계: 제목+URL 중복 제거 ────────────────────────────────
    unique = dedup_by_title(all_articles)
    print(f"중복 제거 후: {len(unique)}건")

    # ── 3단계: 제외 키워드 필터링 (AI 없이) ─────────────────────
    filtered = [a for a in unique if not is_excluded(a.get("title",""), a.get("description",""))]
    print(f"제외 필터 후: {len(filtered)}건")

    # ── 4단계: 이미 전송한 기사 제외 ────────────────────────────
    new_articles = [a for a in filtered if make_hash(a) not in sent_hashes]
    print(f"신규 기사: {len(new_articles)}건\n")

    if not new_articles:
        sender.send_message("📭 [뉴스봇] 신규 관련 기사가 없습니다.")
        return

    # ── 5단계: AI 요약 (남은 기사만, 한줄 요약) ─────────────────
    print("AI 요약 시작...")
    analyzed = summarizer.analyze_articles(new_articles)
    print(f"최종 전송 대상: {len(analyzed)}건\n")

    if not analyzed:
        sender.send_message("📭 [뉴스봇] 관련 기사가 없습니다.")
        return

    # ── 6단계: 텔레그램 전송 ─────────────────────────────────────
    today_str = date.today().strftime("%Y년 %m월 %d일")
    header = f"📰 {today_str} 언론동향 브리핑\n법무부 출입국·외국인정책본부\n{'━'*30}"
    sender.send_message(header)

    new_hashes = set()
    for i, article in enumerate(analyzed, 1):
        msg = formatter.format_response(article, index=i)
        sender.send_message(msg)
        new_hashes.add(make_hash(article))
        print(f"  전송: {article.get('title','')[:40]}...")

    sent_hashes.update(new_hashes)
    save_history(sent_hashes)

    footer = f"✅ 총 {len(analyzed)}건 전송 완료 | {datetime.now().strftime('%H:%M')}"
    sender.send_message(footer)
    print(f"\n완료: {len(analyzed)}건")


if __name__ == "__main__":
    main()
