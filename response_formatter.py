"""
법무부 출입국·외국인정책본부 언론대응 포맷 생성 모듈
- 심플 버전: 제목, 언론사, 링크, 한줄요약만
- 사실관계/향후계획/대응방향 자동생성 제거
"""

import re


class ResponseFormatter:

    def format_response(self, article: dict, index: int = 1) -> str:

        title = article.get("title", "")
        source = article.get("source", "알 수 없음")
        pub_date = article.get("pubDate", "")
        link = article.get("link", "")
        summary = article.get("summary", article.get("description", ""))

        date_str = self._format_date(pub_date)
        summary = self._clean_summary(summary)

        msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{index}번 기사

제목: {title}
언론사: {source} | {date_str}
링크: {link}

요약: {summary}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

        return msg

    def _clean_summary(self, text: str) -> str:
        """JSON 찌꺼기 제거 및 정리"""
        # JSON 블록 제거
        text = re.sub(r'```json.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'\{.*?\}', '', text, flags=re.DOTALL)
        # 백틱 제거
        text = text.replace('`', '')
        # 연속 빈줄 정리
        text = re.sub(r'\n{3,}', '\n', text)
        return text.strip() or "내용 확인 필요"

    def _format_date(self, pub_date_str: str) -> str:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub_date_str)
            return dt.strftime("%m/%d %H:%M")
        except Exception:
            return pub_date_str[:16] if pub_date_str else ""
