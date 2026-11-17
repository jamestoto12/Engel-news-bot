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

□ 「기사 제목」(언론사, {item.get('date', '')})
                                              [지역체류지원과]

[기사 내용]
 ○ 기사의 핵심 주장 한 문장 (~라고 보도 / ~를 지적)
  - 핵심 주장을 받치는 구체 내용 1~2개
  ※ 기사가 근거로 든 수치·일정 등 보조 정보 (있을 때만)

○ (사실확인) 기사 내용 중 우리 기관이 확인할 사실
 - 세부 사실
 ※ (보조 태그) 보충 설명

○ (대응계획) 우리부는 ~할 예정

작성 참고(제출 시 삭제)
- 확인 필요 항목과 확인처
- 대응계획 선택지와 권고

[분량] 한글 15pt, 좌우 여백 20mm 기준 한 줄 33~37자. 기사 내용은 5~7줄(200자 안팎). 사실확인·대응계획은 각각 ○ 1개에 - 또는 ※ 1~2개. 전체 1쪽 이내.

[원칙]
1. 기사 내용에는 기사에 나온 것만 쓴다. 기사에 없는 평가나 우리 기관 입장을 넣지 않는다.
2. 사실확인에는 기사와 일반에 알려진 제도로 확인되는 것만 쓴다. 인원·처분 결과·지자체별 현황처럼 확인하지 못한 수치는 지어내지 말고 [확인 필요: 어디서]로 둔다.
3. 법령 조문 번호, 법무부 내부 지침의 조문·문안을 만들어 쓰지 않는다. 필요하면 "근거 조문 확인 필요"라고 쓴다.
4. 모든 문장에 주어를 쓴다(우리부는, ○○시는, 기사는).
5. 계절근로 건의 대응계획은 끝에 "(가안)"을 붙이고, 선택지가 갈리면 작성 참고에 적는다. 계절근로·E-9·E-10·수산 인력이 아닌 건(E-7, 광역형 비자 등)은 대응계획에 "소관 부서 확인 필요"라고만 쓴다.
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
