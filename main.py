"""
법무부 출입국·외국인정책본부 언론대응 뉴스봇
- AI 없이 운영 (중복제거 + 키워드 필터만)
"""

import os
import json
import hashlib
from datetime import datetime, timedelta, timezone
from news_collector import NewsCollector
from telegram_sender import TelegramSender
from response_formatter import ResponseFormatter
from google_rss_collector import GoogleRSSCollector

# ── 관심 키워드 ──────────────────────────────────────────────────
KEYWORDS = [
    "계절근로",
    "계절노동",
    "외국인 선원",
    "어선 외국인",
    "수산 외국인",
    "해수부 외국인",
    "어선 사고",
    "외국인력 수산",
    # 아래는 '정시 정책 현안 모니터링' 봇에서 쓰던 검색어 (메시지 통일하며 이관)
    "외국인력 도입",
    "양식장 외국인",
    "어촌 외국인",
    "농촌 외국인",
    "외국인 어업",
    "농어촌 일손",
]

# ── 제목에 반드시 포함돼야 할 키워드 (제목 필터) ─────────────────
# 아래 중 하나라도 제목에 있어야 전송
TITLE_MUST_INCLUDE = [
    "외국인 근로자", "외국인 선원", "외국인 계절", "외국인 어선",
    "외국인 어선원", "외국인력", "계절근로", "불법체류",
    "비자", "E-8", "E-9", "E-10", "출입국 정책",
    "수산 인력", "어업 인력", "이민 정책",
    "계절노동", "계절 노동", "계절 근로", "외국인 노동자",
]

# ── 긴급 알림 (MODE=urgent) ──────────────────────────────────────
# 15분마다 실행. 아래 '담당 분야' 단어와 '부정적 단어'가 제목에 함께 있는 최근 기사만 즉시 전송
URGENT_KEYWORDS = ["계절근로", "계절노동", "외국인 선원", "외국인 어선원"]
URGENT_SCOPE = ["계절근로", "계절노동", "계절 근로", "계절 노동", "외국인 선원", "외국인 어선원"]
URGENT_NEGATIVE = [
    "사망", "숨져", "숨진", "숨지", "사고", "부상", "중상", "폭행", "성폭", "성추행", "성희롱",
    "이탈", "도주", "잠적", "불법", "강제출국", "출국 조치", "추방", "인권", "착취", "브로커",
    "체불", "갑질", "학대", "차별", "논란", "문제", "의혹", "비판", "지적", "부실", "허점",
    "구멍", "사각지대", "유명무실", "국감", "국정감사", "국회", "행정사무감사", "단독",
    "적발", "구속", "송치", "음주", "범죄", "마약", "화재", "비리", "피해", "위반", "고발",
    "소송", "강제", "열악", "과잉", "적자", "반발", "규탄",
]
URGENT_WINDOW_HOURS = 3  # 최근 몇 시간 안에 나온 기사만 긴급 대상으로 봄

HISTORY_FILE = "sent_history.json"

# GitHub Actions 러너는 UTC 기준이므로 날짜·시각은 모두 KST로 계산
KST = timezone(timedelta(hours=9))

# 하루 3번 정해진 시각(KST)에 전송
# 정시 실행은 외부 예약 서비스(cron-job.org)가 GitHub에 실행 명령(workflow_dispatch)을 보내서 함.
# 실행되면 '가장 최근에 지난 전송 시각'을 찾아, 그 회차를 아직 안 보냈을 때만 전송
# (GitHub 예비 예약이나 cron-job.org 재시도와 중복 방지)
# 전송 시각을 바꾸려면 이 목록과 cron-job.org 예약 시각을 함께 바꿀 것
SEND_SLOTS = ["07:00", "11:30", "18:00"]
# 예약 지연으로 자정~06시에 실행되면 알림음 없이 전송
NIGHT_UNTIL_HOUR = 6


def now_kst() -> datetime:
    return datetime.now(KST)


def current_slot(now: datetime) -> str:
    """가장 최근에 지난 전송 회차 (예: '2026-10-19 11:30'). 첫 시각 이전이면 전날 마지막 회차"""
    slots = sorted(SEND_SLOTS)
    passed = [s for s in slots if now.strftime("%H:%M") >= s]
    if passed:
        return f"{now.date()} {passed[-1]}"
    return f"{(now - timedelta(days=1)).date()} {slots[-1]}"


def load_history() -> dict:
    """전송 기록: hashes(기사 해시, 오래된 순), titles(최근 전송 제목), last_run_kst(마지막 브리핑 회차)"""
    data = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    data = json.loads(content)
        except (json.JSONDecodeError, Exception):
            data = {}
    return {
        "hashes": list(data.get("hashes", [])),
        "titles": list(data.get("titles", [])),
        "last_run_kst": data.get("last_run_kst", ""),
    }


def save_history(history: dict):
    # 순서를 유지해 가장 오래된 기록부터 버림 (set으로 자르면 최근 기록이 빠져 재전송됨)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "hashes": list(dict.fromkeys(history["hashes"]))[-2000:],
            "titles": list(dict.fromkeys(history["titles"]))[-400:],
            "updated": str(now_kst().date()),
            "last_run_kst": history["last_run_kst"],
        }, f, ensure_ascii=False, indent=2)


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


SIMILAR_THRESHOLD = 0.35


def group_similar(articles: list) -> list:
    """같은 사건을 다룬 기사를 하나로 묶음. 대표 기사에 'similar'(묶인 다른 기사 목록)를 붙여 반환"""
    seen_links = set()
    groups = []  # (대표 기사, 대표 단어집합)
    for art in articles:
        link = art.get("link", "")
        if link in seen_links:
            continue
        seen_links.add(link)
        words = get_title_words(art.get("title", ""))
        for rep_art, rep_words in groups:
            if jaccard_sim(words, rep_words) >= SIMILAR_THRESHOLD:
                rep_art["similar"].append(art)
                break
        else:
            art["similar"] = []
            groups.append((art, words))
    return [g[0] for g in groups]


def is_similar_to_sent(title: str, sent_word_sets: list) -> bool:
    """이미 보낸 기사와 같은 사건인지 (다른 언론사가 다른 제목으로 쓴 경우 포함)"""
    words = get_title_words(title)
    return any(jaccard_sim(words, w) >= SIMILAR_THRESHOLD for w in sent_word_sets)


def published_within(article: dict, hours: int, now: datetime) -> bool:
    dt = article.get("pub_datetime")  # 수집기는 KST 기준 시각(tz 없음)으로 줌
    if not dt:
        return False
    return now.replace(tzinfo=None) - dt <= timedelta(hours=hours)


def collect(keywords: list, naver: "NewsCollector", google, display: int) -> list:
    articles = []
    for keyword in keywords:
        n = naver.search(keyword, display=display)
        g = google.search(keyword, days=3) if google else []
        articles.extend(n)
        articles.extend(g)
        print(f"  [{keyword}] 네이버:{len(n)} + 구글:{len(g)}")
    print(f"\n총 수집: {len(articles)}건")
    return articles


def pick_new(articles: list, title_ok, history: dict) -> list:
    """제목 필터 → 이미 보낸 기사·같은 사건 제외 → 같은 사건끼리 묶기 (이 순서가 중요)"""
    filtered = [a for a in articles if title_ok(a.get("title", ""))]
    print(f"제목 필터 후: {len(filtered)}건")
    sent_hashes = set(history["hashes"])
    sent_words = [get_title_words(t) for t in history["titles"]]
    fresh = [a for a in filtered
             if make_hash(a) not in sent_hashes and not is_similar_to_sent(a.get("title", ""), sent_words)]
    print(f"이미 보낸 기사·같은 사건 제외 후: {len(fresh)}건")
    fresh.sort(key=lambda a: a.get("pub_datetime") or datetime.min, reverse=True)
    grouped = group_similar(fresh)
    print(f"같은 사건 묶은 후: {len(grouped)}건\n")
    return grouped


def record_sent(history: dict, groups: list):
    for art in groups:
        for a in [art] + art.get("similar", []):
            history["hashes"].append(make_hash(a))
        history["titles"].append(art.get("title", ""))


def format_group(formatter, art: dict, index: int) -> str:
    msg = formatter.format_response(art, index=index)
    others = art.get("similar", [])
    if others:
        names = list(dict.fromkeys(o.get("source", "") for o in others if o.get("source")))
        msg += f"\n   ➕ 같은 내용 {len(others)}건 더" + (f" ({', '.join(names[:3])}{' 등' if len(names) > 3 else ''})" if names else "")
    return msg


def is_urgent(title: str) -> bool:
    return any(k in title for k in URGENT_SCOPE) and any(k in title for k in URGENT_NEGATIVE)


def run_urgent(now, history, collector, sender, formatter):
    articles = collect(URGENT_KEYWORDS, collector, None, display=50)
    recent = [a for a in articles if published_within(a, URGENT_WINDOW_HOURS, now)]
    print(f"최근 {URGENT_WINDOW_HOURS}시간 기사: {len(recent)}건")
    groups = pick_new(recent, is_urgent, history)
    if not groups:
        print("긴급 기사 없음 → 전송 생략")
        return
    parts = [f"🚨 [긴급] 대응 검토 필요 기사 {len(groups)}건 | {now.strftime('%m/%d %H:%M')}", "━" * 20, ""]
    for i, art in enumerate(groups, 1):
        parts.append(format_group(formatter, art, i))
        parts.append("")
        print(f"  긴급: {art.get('title','')[:40]}...")
    parts.append("※ 대응이 필요하면 링크를 Claude에 붙이고 '대응 필요'라고 하세요 (사전보고 초안 작성)")
    if not sender.send_message("\n".join(parts), silent=now.hour < NIGHT_UNTIL_HOUR):
        print("\n텔레그램 전송 실패 → 전송 기록을 남기지 않음")
        raise SystemExit(1)
    record_sent(history, groups)
    save_history(history)
    print(f"\n긴급 전송 완료: {len(groups)}건")


def main():
    print(f"\n{'='*60}")
    now = now_kst()
    mode = os.environ.get("MODE", "").strip() or "briefing"
    print(f"뉴스봇 실행({mode}): {now.strftime('%Y-%m-%d %H:%M:%S')} KST")
    print(f"{'='*60}\n")

    history = load_history()

    collector = NewsCollector(os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET"))
    sender = TelegramSender(os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID"))
    formatter = ResponseFormatter()

    if mode == "urgent":
        run_urgent(now, history, collector, sender, formatter)
        return

    forced = os.environ.get("FORCE_RUN") == "1"  # '강제 실행'을 체크한 수동 실행은 회차 제한 없음
    # 수동 실행은 회차 기록을 바꾸지 않음 (다음 정시 브리핑이 막히지 않도록)
    run_slot = history["last_run_kst"] if forced else current_slot(now)
    if not forced and history["last_run_kst"] == run_slot:
        print(f"{run_slot} 회차 이미 전송됨 → 건너뜀")
        return

    # ── 1단계: 수집 (검색어당 최대 100건 — 10건이면 기사 많은 날 통째로 누락됨) ──
    articles = collect(KEYWORDS, collector, GoogleRSSCollector(), display=100)

    # ── 2단계: 제목 필터 → 이미 보낸 기사 제외 → 같은 사건 묶기 ──
    groups = pick_new(articles, title_filter, history)
    history["last_run_kst"] = run_slot

    if not groups:
        print("신규 기사 없음 → 전송 생략")
        save_history(history)
        return

    # ── 3단계: 전송 (하나의 메시지로 합쳐서) ──
    parts = [f"📰 {now.strftime('%Y년 %m월 %d일')} 언론동향 브리핑"]
    parts.append("법무부 출입국·외국인정책본부")
    parts.append(f"총 {len(groups)}건 | {now.strftime('%H:%M')}")
    parts.append("━" * 30)
    parts.append("")
    for i, art in enumerate(groups, 1):
        parts.append(format_group(formatter, art, i))
        parts.append("")
        print(f"  포함: {art.get('title','')[:40]}...")

    if not sender.send_message("\n".join(parts), silent=now.hour < NIGHT_UNTIL_HOUR):
        # 전송 실패 시 기록하지 않음 → 다음 실행에서 같은 기사를 다시 보냄
        print("\n텔레그램 전송 실패 → 전송 기록을 남기지 않음")
        raise SystemExit(1)

    record_sent(history, groups)
    save_history(history)
    print(f"\n완료: {len(groups)}건")


if __name__ == "__main__":
    main()
