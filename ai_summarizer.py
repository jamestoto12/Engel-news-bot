"""
Gemini API를 활용한 뉴스 요약 및 언론대응 필요성 판단 모듈
+ 유사도 검사 기능 추가 (비슷한 기사 자동 제거)
"""

import json
import urllib.request
import urllib.error


class AISummarizer:
    # Gemini 1.5 Flash (무료 티어)
    API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def remove_duplicates(self, articles: list) -> list:
        """
        유사도 검사 - 비슷한 기사 제거
        Gemini가 기사 목록을 읽고 유사한 것끼리 묶어서 대표 1개만 남김
        """
        if len(articles) <= 1:
            return articles

        print(f"  유사도 검사 시작: {len(articles)}건")

        # Gemini에게 넘길 기사 목록 만들기
        article_list = ""
        for i, a in enumerate(articles):
            article_list += f"[{i}] 제목: {a.get('title','')}\n"
            article_list += f"    내용: {a.get('description','')[:100]}\n"
            article_list += f"    언론사: {a.get('source','')}\n\n"

        prompt = f"""아래 뉴스 기사 목록에서 내용이 70% 이상 비슷한 기사들을 찾아주세요.
비슷한 기사끼리 묶고, 각 묶음에서 언론사 영향력이 가장 큰 기사 1개만 남겨주세요.

언론사 영향력 순서 (높은 순):
연합뉴스 > KBS > MBC > SBS > JTBC > YTN > 조선일보 > 중앙일보 > 동아일보 > 한겨레 > 경향신문 > 그 외

[기사 목록]
{article_list}

응답은 JSON만, 다른 설명 없이:
{{
  "keep": [남길 기사 번호 목록, 예: 0, 2, 4],
  "reason": "간단한 이유"
}}"""

        try:
            response = self._call_gemini(prompt)

            # JSON 파싱
            clean = response.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0]
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0]

            parsed = json.loads(clean.strip())
            keep_indices = parsed.get("keep", list(range(len(articles))))
            reason = parsed.get("reason", "")

            # 유효한 인덱스만 필터
            keep_indices = [i for i in keep_indices if 0 <= i < len(articles)]

            result = [articles[i] for i in keep_indices]
            removed = len(articles) - len(result)

            print(f"  유사도 검사 완료: {removed}건 제거 ({reason})")
            return result

        except Exception as e:
            print(f"  [유사도 검사 오류] {e} → 원본 그대로 사용")
            return articles

    def analyze_articles(self, articles: list) -> list:
        """
        1단계: 유사도 검사로 중복 제거
        2단계: 기사별 AI 분석 (요약, 중요도, 사실관계 등)
        """
        # 1단계: 유사도 검사
        articles = self.remove_duplicates(articles)

        # 2단계: 개별 분석
        results = []
        for article in articles:
            try:
                analyzed = self._analyze_single(article)
                results.append(analyzed)
            except Exception as e:
                print(f"  [AI오류] {article.get('title','')[:30]}: {e}")
                article["importance"] = 2
                article["summary"] = article.get("description", "")[:200]
                article["fact_check"] = "확인 필요"
                article["fact_details"] = []
                article["response_type"] = "검토 필요"
                article["future_plan"] = "관계부처 협의 후 입장 결정 예정"
                results.append(article)

        return results

    def _analyze_single(self, article: dict) -> dict:
        """단일 기사 분석"""
        prompt = self._build_prompt(article)
        response_text = self._call_gemini(prompt)

        try:
            clean = response_text.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0]
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0]

            parsed = json.loads(clean.strip())

            article.update({
                "importance": int(parsed.get("importance", 2)),
                "summary": parsed.get("summary", ""),
                "media_tone": parsed.get("media_tone", "중립"),
                "fact_check": parsed.get("fact_check", "확인 필요"),
                "fact_details": parsed.get("fact_details", []),
                "response_type": parsed.get("response_type", ""),
                "future_plan": parsed.get("future_plan", ""),
            })

        except (json.JSONDecodeError, IndexError):
            article["importance"] = 3
            article["summary"] = response_text[:300]
            article["fact_check"] = "AI 분석 중 오류"
            article["fact_details"] = []
            article["response_type"] = "검토 필요"
            article["future_plan"] = "관계부처 협의 후 입장 결정 예정"

        return article

    def _build_prompt(self, article: dict) -> str:
        title = article.get("title", "")
        description = article.get("description", "")
        source = article.get("source", "")
        keyword = article.get("keyword", "")

        return f"""당신은 대한민국 법무부 출입국·외국인정책본부의 언론대응 전문 분석관입니다.
아래 뉴스 기사를 분석하여 JSON 형식으로만 응답하세요.

[기사 정보]
- 언론사: {source}
- 검색키워드: {keyword}
- 제목: {title}
- 내용 요약: {description}

[분석 기준]
- 담당 업무: E-8/E-9 계절근로자 비자, 수산업 외국인력, 어업경영체, 양식업 자동화, 해수부·법무부 정책
- 관련 기관: 법무부, 해양수산부, 고용노동부, 수협

[응답 형식 - JSON only]
{{
  "importance": 1~5 (5=매우 중요 대응필수 / 3=보통 / 1=무관),
  "summary": "기사 내용 2~3문장 요약 (육하원칙 기반)",
  "media_tone": "비판적" 또는 "우호적" 또는 "중립",
  "fact_check": "사실" 또는 "일부사실" 또는 "사실무근" 또는 "확인필요",
  "fact_details": [
    "ㅇ 사실관계 항목1 - 상세내용",
    " - 세부내용",
    "ㅇ 사실관계 항목2 - 상세내용",
    " - 세부내용",
    "ㅇ 사실관계 항목3 - 상세내용"
  ],
  "response_type": "적극해명" 또는 "참고자료 배포" 또는 "모니터링" 또는 "대응불필요",
  "future_plan": "향후 계획 1~2문장 (공무원 문체)"
}}

중요: JSON만 출력하고 다른 설명은 하지 마세요."""

    def _call_gemini(self, prompt: str) -> str:
        """Gemini API 호출"""
        url = f"{self.API_URL}?key={self.api_key}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 1024,
            }
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        return result["candidates"][0]["content"]["parts"][0]["text"]
