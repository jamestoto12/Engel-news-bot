"""
법무부 출입국·외국인정책본부 언론대응 포맷 생성 모듈
- plain text 기반 (특수문자 최소화)
- 공문서 스타일: ㅇ / - 계층 구조
"""

from datetime import datetime


class ResponseFormatter:

    TONE_EMOJI = {
        "비판적": "🔴",
        "우호적": "🟢",
        "중립": "🟡",
    }

    IMPORTANCE_LABEL = {
        5: "🚨 긴급대응",
        4: "⚠️ 적극해명",
        3: "📋 참고자료",
        2: "👀 모니터링",
        1: "ℹ️ 참고",
    }

    def format_response(self, article: dict, index: int = 1) -> str:
        """언론대응 텔레그램 메시지 포맷 생성"""

        title = article.get("title", "")
        source = article.get("source", "알 수 없음")
        pub_date = article.get("pubDate", "")
        link = article.get("link", "")
        summary = article.get("summary", article.get("description", ""))
        fact_check = article.get("fact_check", "확인 필요")
        fact_details = article.get("fact_details", [])
        future_plan = article.get("future_plan", "관계부처 협의 후 입장 결정 예정")
        importance = article.get("importance", 3)
        media_tone = article.get("media_tone", "중립")
        response_type = article.get("response_type", "모니터링")

        tone_emoji = self.TONE_EMOJI.get(media_tone, "🟡")
        importance_label = self.IMPORTANCE_LABEL.get(importance, "📋 참고자료")
        date_str = self._format_date(pub_date)

        # summary에서 JSON 찌꺼기 제거
        summary = self._clean_summary(summary)

        # 사실관계 항목 포맷
        if not fact_details:
            fact_details = [
                f"ㅇ {fact_check} - 세부 사실관계 확인 필요",
                "  - 관련 법령 및 정책 검토 중",
            ]
        fact_block = "\n".join(fact_details)

        msg = f"""{'━'*30}
{importance_label} | {tone_emoji} {media_tone} | {index}번 기사

제목: {title}
언론사: {source} | {date_str}
링크: {link}

【 배경 】
{summary}

【 사실관계 [{fact_check}] 】
{fact_block}

【 향후 계획 】
ㅇ {future_plan}

대응방향: {response_type}
{'━'*30}"""

        return msg

    def _clean_summary(self, text: str) -> str:
        """summary에 JSON이 섞여있으면 제거"""
        import re
        import json as jsonlib

        # JSON 블록 제거
        text = re.sub(r'```json.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

        # { 로 시작하는 JSON 덩어리 제거
        text = re.sub(r'\{.*?\}', '', text, flags=re.DOTALL)

        # 백틱, 따옴표 정리
        text = text.replace('`', '').replace('"importance"', '').replace('"summary"', '')

        # 연속 빈줄 정리
        text = re.sub(r'\n{3,}', '\n', text)

        return text.strip() or "내용 확인 필요"

    def _format_date(self, pub_date_str: str) -> str:
        """날짜 포맷 정리"""
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub_date_str)
            return dt.strftime("%m/%d %H:%M")
        except Exception:
            return pub_date_str[:16] if pub_date_str else ""
