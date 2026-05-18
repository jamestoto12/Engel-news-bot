"""
Gemini API를 활용한 뉴스 분석 모듈
- 역할 1: 유사도 검사 (비슷한 기사 묶기)
- 역할 2: 관련성 필터링 (무관 기사 제거)
- 역할 3: 한줄 요약
- 중요도 점수 없음
"""

import json
import urllib.request
import time


class AISummarizer:
    API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def analyze_articles(self, articles: list) -> list:
        """
        1단계: 유사도 검사 (중복 제거)
        2단계: 관련성 필터링 + 한줄 요약
        """
        if not articles:
            return []

        # 1단계: 유사도 검사
        articles = self._remove_similar(articles)

        # 2단계: 관련성 필터링 + 요약
        results = []
        for article in articles:
            time.sleep(3)  # API 한도 초과 방지
            try:
                result = self._filter_and_summarize(article)
                if result:  # None이면 무관 기사로 제거
                    results.append(result)
            except Exception as e:
                print(f"  [AI오류] {article.get('title','')[:30]}: {e}")
                # AI 실패 시 일단 포함 (요약은 description으로 대체)
                article["summary"] = article.get("description", "")[:150]
                results.append(article)

        return results

    def _remove_similar(self, articles: list) -> list:
        """유사도 검사 - 비슷한 기사 제거"""
        if len(articles) <= 1:
            return articles

        print(f"  유사도 검사 시작: {len(articles)}건")

        article_list = ""
        for i, a in enumerate(articles):
            article_list += f"[{i}] {a.get('title','')[:50]} ({a.get('source','')})\n"

        prompt = f"""아래 뉴스 기사 목록에서 내용이 70% 이상 비슷한 기사끼리 묶고,
각 묶음에서 언론사 영향력이 가장 큰 기사 1개만 남겨주세요.

언론사 영향력 순서: 연합뉴스 > KBS > MBC > SBS > JTBC > YTN > 조선 > 중앙 > 동아 > 한겨레 > 그 외

[기사 목록]
{article_list}

JSON만 응답:
{{"keep": [남길 번호들], "reason": "이유"}}"""

        try:
            time.sleep(3)
            response = self._call_gemini(prompt)
            clean = response.strip()
            if "```json" in clean:
                clean = clean.split("```json")[1].split("```")[0]
            elif "```" in clean:
                clean = clean.split("```")[1].split("```")[0]

            parsed = json.loads(clean.strip())
            keep_indices = [i for i in parsed.get("keep", []) if 0 <= i < len(articles)]
            result = [articles[i] for i in keep_indices]
            removed = len(articles) - len(result)
            print(f"  유사도 검사 완료: {removed}건 제거")
            return result

        except Exception as e:
            print(f"  [유사도 오류] {e} → 원본 유지")
            return articles

    def _filter_and_summarize(self, article: dict) -> dict:
        """
        관련성 판단 + 한줄 요약
        무관 기사면 None 반환
        """
        title = article.get("title", "")
        description = article.get("description", "")

        prompt = f"""아래 뉴스가 외국인 근로자/계절근로자/어선원/수산업 인력/출입국 정책과
직접 관련이 있으면 YES, 없으면 NO로 판단하고 요약해주세요.

제목: {title}
내용: {description[:200]}

관련 없는 예시: 지방선거, 노약자 복지, 물류단지, 맛집, 단순 봉사활동

JSON만 응답:
{{"relevant": "YES" 또는 "NO", "summary": "관련있으면 한줄요약(50자 이내), 없으면 빈문자열"}}"""

        response = self._call_gemini(prompt)
        clean = response.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0]
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0]

        parsed = json.loads(clean.strip())

        if parsed.get("relevant", "NO") == "NO":
            return None  # 무관 기사 제거

        article["summary"] = parsed.get("summary", "") or description[:150]
        article["importance"] = 3  # 기본값 (전송 조건용)
        return article

    def _call_gemini(self, prompt: str) -> str:
        url = f"{self.API_URL}?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512}
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["candidates"][0]["content"]["parts"][0]["text"]
