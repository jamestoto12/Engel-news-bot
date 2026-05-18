"""
법무부 출입국·외국인정책본부 언론대응 뉴스봇
매일 아침 실행 → 뉴스 수집 → AI 필터링/요약 → 텔레그램 전송
"""

import os
import json
import hashlib
from datetime import datetime, date
from news_collector import NewsCollector
from ai_summarizer import AISummarizer
from telegram_sender import TelegramSender
from response_formatter import ResponseFormatter

# ── 관심 키워드 ──────────────────────────────────────────────────
KEYWORDS = [
    "E-8 계절근로자",
    "E-9 계절근로자",
    "수산업 외국인력",
    "어업경영체 외국인",
    "양식업 자동화",
    "해수부 외국인 근로자",
    "법무부 계절근로",
    "외국인 어선원",
    "비전문취업 수산",
]

# ── 제외 키워드 ───────────────────────────────────────────────────
EXCLUDE_KEYWORDS = [
    "맛집", "요리", "레시피", "할인", "이벤트", "봉사활동",
    "음식점", "셰프", "식당", "축제", "행사 참여", "무료나눔"
]

HISTORY_FILE = "sent_history.json"


def load_history() -> set:
    """이미 전송한 기사 해시 목록 로드"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("hashes", []))
    return set()


def save_history(hashes: set):
    """전송한 기사 해시 목록 저장 (최근 500개만 유지)"""
    hash_list = list(hashes)[-500:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"hashes": hash_list, "updated": str(date.today())}, f, ensure_ascii=False, indent=2)


def make_hash(article: dict) -> str:
    """기사 고유 해시 생성 (중복 체크용)"""
    key = article.get("title", "") + article.get("link", "")
    return hashlib.md5(key.encode()).hexdigest()


def is_excluded(title: str, description: str) -> bool:
    """제외 키워드 포함 여부 확인"""
    text = (title + description).lower()
    return any(kw in text for kw in EXCLUDE_KEYWORDS)


def main():
    print(f"\n{'='*60}")
    print(f"뉴스봇 실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # API 키 환경변수에서 로드
    naver_client_id = os.environ.get("NAVER_CLIENT_ID")
    naver_client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    # 초기화
    collector = NewsCollector(naver_client_id, naver_client_secret)
    summarizer = AISummarizer(gemini_api_key)
    sender = TelegramSender(telegram_token, telegram_chat_id)
    formatter = ResponseFormatter()

    # 이전 전송 기록 로드
    sent_hashes = load_history()

    # 뉴스 수집
    all_articles = []
    for keyword in KEYWORDS:
        articles = collector.search(keyword, display=10)
        all_articles.extend(articles)
        print(f"  [{keyword}] {len(articles)}건 수집")

    print(f"\n총 수집: {len(all_articles)}건")

    # 중복 제거 (URL 기반)
    seen_links = set()
    unique_articles = []
    for art in all_articles:
        link = art.get("link", "")
        if link not in seen_links:
            seen_links.add(link)
            unique_articles.append(art)

    print(f"중복 제거 후: {len(unique_articles)}건")

    # 제외 키워드 필터링
    filtered = [a for a in unique_articles if not is_excluded(a.get("title",""), a.get("description",""))]
    print(f"제외 필터 후: {len(filtered)}건")

    # 이미 전송한 기사 제외
    new_articles = [a for a in filtered if make_hash(a) not in sent_hashes]
    print(f"신규 기사: {len(new_articles)}건\n")

    if not new_articles:
        print("전송할 신규 기사 없음.")
        sender.send_message("📭 [뉴스봇] 오늘 신규 관련 기사가 없습니다.")
        return

    # AI 요약 및 중요도 판단
    print("AI 요약·필터링 시작...")
    analyzed = summarizer.analyze_articles(new_articles)

    # 대응 필요성 높은 기사만 선별 (AI 판단)
    important = [a for a in analyzed if a.get("importance", 0) >= 3]
    print(f"대응 필요 기사: {len(important)}건")

    if not important:
        print("대응 필요성 높은 기사 없음.")
        sender.send_message("📋 [뉴스봇] 오늘 언론대응이 필요한 기사가 없습니다.")
        return

    # 텔레그램 전송
    today_str = date.today().strftime("%Y년 %m월 %d일")
    header = f"📰 *{today_str} 언론동향 브리핑*\n법무부 출입국·외국인정책본부\n{'─'*30}"
    sender.send_message(header)

    new_hashes = set()
    for i, article in enumerate(important, 1):
        # 언론대응 포맷 생성
        response_text = formatter.format_response(article, index=i)
        sender.send_message(response_text)
        new_hashes.add(make_hash(article))
        print(f"  전송 완료: {article.get('title', '')[:40]}...")

    # 전송 기록 저장
    sent_hashes.update(new_hashes)
    save_history(sent_hashes)

    footer = f"\n✅ 총 {len(important)}건 전송 완료 | {datetime.now().strftime('%H:%M')}"
    sender.send_message(footer)
    print(f"\n전송 완료: {len(important)}건")


if __name__ == "__main__":
    main()
