"""
언론 사전보고 초안 작성 모듈
- 기사 본문을 가져와 Gemini로 「출입국·외국인정책본부 언론 사전보고」 초안을 텍스트로 작성
- 양식·원칙은 주무관 저장소의 press-prereport 절차서와 같게 맞춤
"""

import html
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
WEEKDAYS = "월화수목금토일"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
# 앞의 모델이 안 되면 다음 모델로 시도
GEMINI_MODELS = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-pro-latest", "gemini-flash-latest"]


def _get(url: str, timeout: int = 15) -> tuple:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        final = resp.geturl()
        charset = resp.headers.get_content_charset() or ""
    for enc in [charset, "utf-8", "euc-kr", "cp949"]:
        if not enc:
            continue
        try:
            return raw.decode(enc), final
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "ignore"), final


def _strip(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def fetch_article(url: str) -> str:
    """기사 본문을 최대한 뽑아 냄. 못 뽑으면 빈 문자열"""
    try:
        page, _ = _get(url)
    except Exception as e:
        print(f"  [본문 수집 실패] {url}: {e}")
        return ""
    # 네이버 뉴스 본문
    m = re.search(r'<article[^>]*id="dic_area"[^>]*>(.*?)</article>', page, re.S) or \
        re.search(r'<div[^>]*id="(?:dic_area|articleBodyContents|newsct_article)"[^>]*>(.*?)</div>\s*</div>', page, re.S)
    if m:
        return _strip(m.group(1))[:5000]
    # 일반 언론사: 흔히 쓰는 본문 영역을 먼저 찾고, 없으면 문장으로 끝나는 <p> 문단만 모음
    for pat in [r'itemprop="articleBody"[^>]*>(.*?)</(?:div|section|article)>',
                r'id="article-view-content-div"[^>]*>(.*?)</article>',
                r'class="[^"]*(?:article[-_]?body|article[-_]?content|news[-_]?body|view[-_]?con|entry-content|article_txt)[^"]*"[^>]*>(.*?)</(?:div|section|article)>',
                r"<article[^>]*>(.*?)</article>"]:
        m = re.search(pat, page, re.S | re.I)
        if m:
            cand = _strip(m.group(1))
            if len(cand) >= 300:
                return cand[:5000]
    paras = [_strip(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", page, re.S | re.I)]
    paras = [p for p in paras if len(p) >= 40 and re.search(r"(다|요|음)[.”\"']?\s*$", p)]
    body = "\n".join(paras)
    desc = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', page)
    if len(body) < 200 and desc:
        body = html.unescape(desc.group(1)) + "\n" + body
    return body[:5000]


def gather_text(links: list) -> str:
    """같은 보도 링크 중 본문이 충분히 나오는 것을 씀 (구글 링크는 뒤로)"""
    ordered = sorted(links, key=lambda u: "news.google.com" in u)
    best = ""
    for url in ordered:
        text = fetch_article(url)
        if len(text) > len(best):
            best = text
        if len(best) >= 600:
            break
    return best


def build_prompt(item: dict, body: str, today: datetime) -> str:
    report_date = f"'{today:%y}. {today.month}. {today.day}.({WEEKDAYS[today.weekday()]})"
    return f"""너는 법무부 출입국·외국인정책본부 지역체류지원과 주무관이다. 아래 기사로 「출입국·외국인정책본부 언론 사전보고」 초안을 쓴다. 담당 사무관은 계절근로(E-8)를 중심으로 E-9·E-10, 수산 인력을 맡는다.

[양식] 아래 틀을 그대로 쓰고, 한글 보고서에 붙여넣을 수 있게 □ ○ - ※ 기호와 들여쓰기를 지킨다. 마크다운(#, **, ```)은 쓰지 않는다.
        출입국·외국인정책본부 언론 사전보고
                         {report_date} 출입국·외국인정책본부

□ 「기사 제목」({item.get('source', '')}, {item.get('date', '')}.)
                                              [지역체류지원과]

(기사 내용)
 ○ 무엇이 일어났는지 사실 서술 한 문장 (~발생함 / ~배포함)
  - 후속 판단·반응 한 문장 (~판단되었으나 ~제기됨 / ~촉구함)
  ※ 보조 정보 한 줄 (있을 때만)

○ (대응계획) 우리가 할 일 한 문장 (주어 생략, ~할 예정임)
 - 예상 쟁점이나 판단 원칙 한 문장 (~쟁점이 될 것으로 보임 / ~것은 아님)

※ 배경 사실 (기사에 나온 수사·송치·제재 경과가 있을 때만, 2~3줄)

작성 참고(제출 시 삭제)
- 확인 필요 항목과 확인처
- 대응계획 선택지와 권고

[실제 보고본 예시 — 이 문체와 분량을 따른다]
(기사 내용)
 ○ 창원시·김해시 등 일부 지자체가 외국인 계절근로자의 근무태만 신고가 2회 이상 접수되면 근로계약 해지 및 출국 조치하고 정당한 사유 없이 계약을 해지할 경우 추천한 결혼이민자의 가족 초청을 제한하는 내용의 신청 서식을 배포
  - 정의당은 해당 조항이 근로자의 계약 해지 자유를 제한하고 가족에게까지 불이익을 주는 반인권적 조치라며, 조항 폐지 및 전국 지자체 신청 서식 전수점검을 촉구
○ (대응계획) 계절근로 프로그램은 지자체가 운영지침 내 기본요건을 준수하는 범위에서 지역 여건에 따라 자율적으로 운영할 수 있으나, 근로계약 해지는 「근로기준법」 등 관계 법령에 따라 판단하여야 하며, 근무태만 신고 횟수만으로 자동적으로 이뤄지는 것은 아님
 - 해당 지자체의 신청 서식 및 운영 실태를 확인하고 근로계약 해지·출국 조치 및 가족 초청 제한 등 관련 법령과 계절근로 프로그램 운영지침에 부합하지 않는 사항은 시정하도록 개선 안내 예정임

[분량] 한글 15pt, 좌우 여백 20mm 기준 한 줄 33~37자. 기사 내용은 ○ 1개, - 1개, ※ 0~1개. 대응계획은 ○ 1개에 - 1~2개. 전체 1쪽 이내.

[원칙]
1. 기사 내용에는 기사에 나온 것만 사실 서술로 쓴다. "~라고 보도"로 끝내지 않는다. 기사에 없는 평가나 우리 기관 입장을 넣지 않는다.
2. 기본은 (기사 내용)과 (대응계획)뿐이다. (사실확인)은 기사 본문에 기사 주장과 다른 공식 확인 사실(지자체·정부의 해명이나 공식 발표 내용)이 있을 때만 대응계획 앞에 '○ (사실확인)'으로 넣는다. 기사에 나온 수사·제재 경과는 맨 끝 ※에 쓰고, 확인하지 못한 수치는 지어내지 말고 작성 참고에 [확인 필요: 어디서]로 둔다.
3. 법령 조문 번호, 법무부 내부 지침의 조문·문안을 만들어 쓰지 않는다. 법령은 「근로기준법」처럼 이름까지만 쓴다.
4. 대응계획은 관계기관 현황 파악, 법적 책임 범위 검토, 지자체 실태 확인 후 시정 안내처럼 실무적으로 할 수 있는 일로 쓴다. "(가안)" 표시는 하지 않는다. 지자체 운영 문제는 "지자체 자율운영은 가능하나 관계 법령·운영지침 범위 안" 틀로 쓴다.
5. 계절근로·E-9·E-10·수산 인력이 아닌 건(E-7, 광역형 비자 등)은 대응계획에 "소관 부서 확인 필요"라고만 쓴다.
6. 결과는 초안 본문만 출력한다. 앞뒤 인사말이나 설명을 붙이지 않는다.

[기사 정보]
제목: {item.get('title', '')}
언론사: {item.get('source', '')}
보도일: {item.get('date', '')}
링크: {(item.get('links') or [''])[0]}

[기사 본문]
{body if body else '(본문을 가져오지 못함. 제목만으로 쓰되, 기사 내용 칸 첫 줄에 [본문 미확인]이라고 표시)'}
"""


def call_gemini(api_key: str, prompt: str) -> str:
    last_error = ""
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 4096},
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                print(f"  [Gemini] {model} 사용")
                return re.sub(r"```[a-z]*\n?|```", "", text).replace("**", "").strip()
        except Exception as e:
            last_error = f"{model}: {e}"
            print(f"  [Gemini 실패] {last_error}")
    raise RuntimeError(last_error or "Gemini 응답 없음")


def write_prereport(api_key: str, item: dict) -> str:
    body = gather_text(item.get("links", []))
    print(f"  본문 {len(body)}자 확보: {item.get('title', '')[:30]}")
    return call_gemini(api_key, build_prompt(item, body, datetime.now(KST)))
