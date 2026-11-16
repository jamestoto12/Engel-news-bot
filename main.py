"""
법무부 출입국·외국인정책본부 언론대응 뉴스봇
- AI 없이 운영 (중복제거 + 키워드 필터만)
"""

import os
import json
import hashlib
import re
import html
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
# 이 단어가 있으면 무조건 부정적 기사
URGENT_STRONG = [
    "사망", "숨져", "숨진", "숨지", "중상", "폭행", "성폭", "성추행", "성희롱", "강제출국", "출국 조치",
    "추방", "착취", "학대", "구속", "송치", "음주운전", "마약", "화재", "비리", "고발", "소송", "규탄",
    "국감", "국정감사", "단독", "체불", "갑질", "브로커",
]
# 이 단어는 부정적일 수도 있지만, 아래 '긍정 맥락' 단어와 함께 나오면 제외 (예: 안전사고 예방 교육, 이탈 줄어)
URGENT_WEAK = [
    "사고", "부상", "이탈", "도주", "잠적", "불법", "인권", "차별", "논란", "문제", "의혹", "비판",
    "지적", "부실", "허점", "구멍", "사각지대", "유명무실", "국회", "행정사무감사", "적발", "범죄",
    "피해", "위반", "강제", "열악", "과잉", "적자", "반발", "질타", "도마",
]
POSITIVE_CONTEXT = [
    "예방", "방지", "지킨다", "지켜", "보호", "줄어", "감소", "해소", "개선", "강화", "교육", "지원",
    "상생", "모범", "우수", "환영", "협약", "맞손", "캠페인", "안전", "제로",
]
URGENT_NEGATIVE = URGENT_STRONG + URGENT_WEAK  # (하위 호환용 이름)
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


# ── 같은 사건 판단 ─────────────────────────────────────────────
# 언론사마다 조사·표현을 바꿔 써서("닥락성, 사업 협약" / "닥락성과 MOU 체결") 단어 비교로는 못 잡음.
# 그래서 ① 제목에 나온 지자체·기관명(○○시·군·구, ○○농협 등)과 ② 글자 2개 단위 겹침으로 판단.
COMMON_WORDS = ["외국인", "계절근로자", "계절근로", "계절노동자", "계절노동", "근로자", "노동자",
                "공공형", "농가형", "베트남", "필리핀", "라오스", "캄보디아", "몽골", "키르기스스탄",
                "농촌", "농가", "인력난", "일손", "지원", "운영", "추진", "본격", "확대", "올해", "내년"]
ENTITY_RE = re.compile(r"[가-힣]{1,8}(?:특례시|광역시|특별시|시|군|구|농협|수협|축협|의회|교육청)(?=[\s,·\-…'\"‘’“”(]|과|와|은|는|이|가|의|에|서|도|$)")
ENTITY_EXCLUDE = {"도시", "임시", "당시", "동시", "수시", "즉시", "역시", "다시", "일시", "정시", "외국인근로자지원센터"}
SAME_ENTITY_DICE = 0.18   # 같은 지자체·기관이 주어인 제목끼리는 이 정도만 겹쳐도 같은 사건
DIFF_ENTITY_DICE = 0.45   # 지자체가 다르거나 없으면 훨씬 많이 겹쳐야 같은 사건


def title_features(title: str) -> tuple:
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>", " ", title)  # [단독]·(종합) 같은 꼬리표 제거
    entities = {e for e in ENTITY_RE.findall(t) if e not in ENTITY_EXCLUDE}
    core = t
    for w in sorted(COMMON_WORDS, key=len, reverse=True):
        core = core.replace(w, " ")
    for e in entities:
        core = core.replace(e, " ")
    core = re.sub(r"[^0-9A-Za-z가-힣]", "", core)
    bigrams = {core[i:i + 2] for i in range(len(core) - 1)}
    # '진안군'과 '진안 ~', '농협 진안군지부'가 같은 곳을 가리키도록 어간(진안)도 둠
    stems = {re.sub(r"(특례시|광역시|특별시|시|군|구|농협|수협|축협|의회|교육청)$", "", e) for e in entities}
    stems = {st for st in stems if len(st) >= 2}
    return stems, bigrams, re.sub(r"\s", "", t)


def dice(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return 2 * len(a & b) / (len(a) + len(b))


def same_event(f1: tuple, f2: tuple) -> bool:
    e1, b1, t1 = f1
    e2, b2, t2 = f2
    if any(st in t2 for st in e1) or any(st in t1 for st in e2):
        return dice(b1, b2) >= SAME_ENTITY_DICE
    return dice(b1, b2) >= DIFF_ENTITY_DICE


def is_google(art: dict) -> bool:
    return "news.google.com" in art.get("link", "")


def group_similar(articles: list) -> list:
    """같은 사건을 다룬 기사를 하나로 묶음. 대표 기사에 'similar'(묶인 다른 기사 목록)를 붙여 반환"""
    seen_links = set()
    groups = []  # (대표 기사, 묶음 안 모든 기사의 특징 목록)
    for art in articles:
        link = art.get("link", "")
        if link in seen_links:
            continue
        seen_links.add(link)
        feat = title_features(art.get("title", ""))
        for rep_art, feats in groups:
            # 대표 기사뿐 아니라 이미 묶인 기사 중 하나와 같은 사건이어도 같은 묶음
            if any(same_event(feat, f) for f in feats):
                rep_art["similar"].append(art)
                feats.append(feat)
                break
        else:
            art["similar"] = []
            groups.append((art, [feat]))
    reps = []
    for rep, _ in groups:
        # 대표 링크는 구글 암호화 링크보다 네이버·언론사 링크를 우선
        if is_google(rep):
            alt = next((o for o in rep["similar"] if not is_google(o)), None)
            if alt:
                others = [rep] + [o for o in rep["similar"] if o is not alt]
                alt["similar"] = others
                rep = alt
        reps.append(rep)
    return reps


def is_similar_to_sent(title: str, sent_features: list) -> bool:
    """이미 보낸 기사와 같은 사건인지 (다른 언론사가 다른 제목으로 쓴 경우 포함)"""
    f = title_features(title)
    return any(same_event(f, sf) for sf in sent_features)


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
    sent_features = [title_features(t) for t in history["titles"]]
    fresh = [a for a in filtered
             if make_hash(a) not in sent_hashes and not is_similar_to_sent(a.get("title", ""), sent_features)]
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


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def format_group(art: dict, index: int) -> str:
    """제목을 누르면 기사가 열리게(HTML 링크) 두 줄로 표시"""
    title = esc(art.get("title", ""))
    link = esc(art.get("link", ""))
    dt = art.get("pub_datetime")
    when = dt.strftime("%m/%d %H:%M") if dt else ""
    line2 = f"   {esc(art.get('source', ''))} {when}"
    others = art.get("similar", [])
    if others:
        names = list(dict.fromkeys(o.get("source", "") for o in others if o.get("source")))
        line2 += f" · 같은 보도 {len(others)}건 더" + (f"({esc(', '.join(names[:2]))}{' 등' if len(names) > 2 else ''})" if names else "")
    return f'{index}. <a href="{link}">{title}</a>\n{line2}'


def is_negative(title: str) -> bool:
    if any(k in title for k in URGENT_STRONG):
        return True
    return any(k in title for k in URGENT_WEAK) and not any(k in title for k in POSITIVE_CONTEXT)


def is_urgent(title: str) -> bool:
    return any(k in title for k in URGENT_SCOPE) and is_negative(title)


def run_urgent(now, history, collector, sender, formatter):
    articles = collect(URGENT_KEYWORDS, collector, None, display=50)
    recent = [a for a in articles if published_within(a, URGENT_WINDOW_HOURS, now)]
    print(f"최근 {URGENT_WINDOW_HOURS}시간 기사: {len(recent)}건")
    groups = pick_new(recent, is_urgent, history)
    if not groups:
        print("긴급 기사 없음 → 전송 생략")
        return
    parts = [f"🚨 <b>[긴급] 대응 검토 필요 {len(groups)}건</b> | {now.strftime('%m/%d %H:%M')}", ""]
    for i, art in enumerate(groups, 1):
        parts.append(format_group(art, i))
        print(f"  긴급: {art.get('title','')[:40]}...")
    parts.append("")
    parts.append("※ 대응 필요 시 링크를 Claude에 붙이고 '대응 필요'")
    if not sender.send_message("\n".join(parts), silent=now.hour < NIGHT_UNTIL_HOUR, html=True):
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
    negative = [a for a in groups if is_negative(a.get("title", ""))]
    normal = [a for a in groups if not is_negative(a.get("title", ""))]
    total_raw = sum(1 + len(a.get("similar", [])) for a in groups)
    parts = [f"📰 <b>{now.strftime('%m월 %d일 %H:%M')} 언론동향</b> | {len(groups)}건 (기사 {total_raw}건 묶음)", ""]
    i = 0
    if negative:
        parts.append(f"⚠️ <b>주의 ({len(negative)})</b>")
        for art in negative:
            i += 1
            parts.append(format_group(art, i))
        parts.append("")
    if normal:
        parts.append(f"📌 <b>일반 ({len(normal)})</b>")
        for art in normal:
            i += 1
            parts.append(format_group(art, i))
    for art in negative + normal:
        print(f"  포함: {art.get('title','')[:40]}...")

    if not sender.send_message("\n".join(parts), silent=now.hour < NIGHT_UNTIL_HOUR, html=True):
        # 전송 실패 시 기록하지 않음 → 다음 실행에서 같은 기사를 다시 보냄
        print("\n텔레그램 전송 실패 → 전송 기록을 남기지 않음")
        raise SystemExit(1)

    record_sent(history, groups)
    save_history(history)
    print(f"\n완료: {len(groups)}건")


if __name__ == "__main__":
    main()
