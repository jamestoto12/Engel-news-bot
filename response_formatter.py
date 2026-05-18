"""
언론대응 포맷 - 제목, 언론사, 날짜, 링크만 (요약 없음)
"""


class ResponseFormatter:

    def format_response(self, article: dict, index: int = 1) -> str:
        title = article.get("title", "")
        source = article.get("source", "알 수 없음")
        pub_date = article.get("pubDate", "")
        link = article.get("link", "")
        date_str = self._format_date(pub_date)

        msg = f"""[{index}] {title}
   📰 {source} | {date_str}
   🔗 {link}"""

        return msg

    def _format_date(self, pub_date_str: str) -> str:
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(pub_date_str)
            return dt.strftime("%m/%d %H:%M")
        except Exception:
            return pub_date_str[:16] if pub_date_str else ""
