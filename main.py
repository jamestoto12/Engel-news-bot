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
    "계절근로",
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
    "외국인 근로자", "외국인 선원", "외국인 계절", "외국인 어선",
    "외국인 어선원", "외국인력", "계절근로", "불법체류",
    "비자", "E-8", "E-9", "E-10", "출입국 정책",
    "수산 인력", "어업 인력", "이민 정책",
]

HISTORY_FILE = "sent_history.json"


def load_history() -> set:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return set()
                data = json.loads(content)
                return set(data.get("hashes", []))
        except (json.JSONDecodeError, Exception):
            return set()
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


def get_title_words(title: str) -> set:
    """제목에서 핵심 단어 추출 (불용어 제거, 조사 정규화)"""
    import re
    title = re.sub(r'[^\w\s]', ' ', title)
    stopwords = {
        '외국인', '계절근로자', '계절근로', '총력', '본격', '운영',
        '무료', '포함', '해소', '투입', '농번기', '공공형',
        '연속', '농사', '일손', '이미', '맞춤형'
    }
    # 단어 앞 4글자로 정규화 (조사 차이 흡수: 흉기 vs 흉기로)
    words = set(w[:4] for w in title.split() if len(w) >= 2)
    return words - stopwords


def jaccard_sim(w1: set, w2: set) -> float:
    """두 단어 집합 유사도"""
    if not w1 or not w2:
        return 0.0
    return len(w1 & w2) / len(w1 | w2)


# 지역명 목록 (중복 판단용)
REGION_WORDS = [
    '영동군', '전남', '전라남', '인천', '경북', '경상북', '해남', '강화군',
    '정읍', '고흥', '울산', '목포', '포천', '부산', '제주', '여수',
    '광주', '대전', '세종', '충남', '충청남', '충북', '강원', '경남', '경기',
]

# 사건종류 키워드 (중복 판단용)
EVENT_WORDS = [
    '계절근로', '구급약품', '흉기', '주치의', '원격진료',
    '인력난', '브로커', '법제화', '전담', '사고', '입국',
]


def get_event_key(title: str) -> str:
    """지역명+사건종류 조합 키 생성"""
    region = next((r for r in REGION_WORDS if r in title), "")
    event = next((e for e in EVENT_WORDS if e in title), "")
    return f"{region}_{event}" if region and event else ""


def dedup(articles: list) -> list:
    """URL 중복 + 제목 유사도 + 지역/사건 조합 기준 중복 제거"""
    # 1차: URL 중복 제거
    seen_links = set()
    url_deduped = []
    for art in articles:
        link = art.get("link", "")
        if link not in seen_links:
            seen_links.add(link)
            url_deduped.append(art)

    # 2차: 유사도 + 지역/사건 조합 중복 제거
    kept = []
    kept_words = []
    seen_event_keys = set()

    for art in url_deduped:
        title = art.get("title", "")
        words = get_title_words(title)
        event_key = get_event_key(title)

        # 지역+사건 조합이 이미 있으면 중복
        if event_key and event_key in seen_event_keys:
            continue

        # 유사도 중복
        if any(jaccard_sim(words, kw) >= 0.35 for kw in kept_words):
            continue

        kept.append(art)
        kept_words.append(words)
        if event_key:
            seen_event_keys.add(event_key)

    return kept


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
