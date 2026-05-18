"""
법무부 출입국·외국인정책본부 언론대응 포맷 생성 모듈
공문서 스타일: ㅇ / - 계층 구조
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
        """
        언론대응 텔레그램 메시지 포맷 생성
        """
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

        # 날짜 포맷
        date_str = self._format_date(pub_date)

        # 사실관계 항목 포맷 (없으면 기본값)
        if not fact_details:
            fact_details = [
                f"ㅇ {fact_check} - 세부 사실관계 확인 필요",
                "- 관련 법령 및 정책 검토 중",
            ]

        fact_block = "\n".join(fact_details)

        # 이스케이프 처리 (텔레그램 MarkdownV2 특수문자)
        # 일반 Markdown 사용
        msg = f"""{'━'*35}
{importance_label} | {tone_emoji} {media_tone} | {index}번 기사

📌 *제목*: {title}
🗞 *언론사*: {source} | {date_str}
🔗 {link}

━━━ 배경 ━━━━━━━━━━━━━━━━━━━
{summary}

━━━ 사실관계 [{fact_check}] ━━━━━━━
{fact_block}

━━━ 향후 계획 ━━━━━━━━━━━━━━
ㅇ {future_plan}

💬 *대응 방향*: {response_type}
{'━'*35}"""

        return msg

    def format_daily_summary(self, articles: list) -> str:
        """하루 전체 브리핑 요약"""
        total = len(articles)
        urgent = sum(1 for a in articles if a.get("importance", 0) >= 4)
        critical = sum(1 for a in articles if a.get("media_tone") == "비판적")

        return f"""
📊 *오늘의 동향 요약*
- 대응 필요 기사: 총 {total}건
- 긴급/적극해명: {urgent}건
- 비판적 보도: {critical}건
"""

    def _format_date(self, pub_date_str: str) -> str:
        """날짜 포맷 정리"""
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub_date_str)
            return dt.strftime("%m/%d %H:%M")
        except Exception:
            return pub_date_str[:16] if pub_date_str else ""
