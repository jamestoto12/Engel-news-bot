"""
구글 뉴스 RSS를 통한 뉴스 수집 모듈
- 네이버 API에서 못 잡는 지역지·전문지 커버
- 추가 API 키 불필요 (무료)
"""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta


class GoogleRSSCollector:

    BASE_URL = "https://news.google.com/rss/search"

    def __init__(self):
        pass

    def search(self, keyword: str, days: int = 3) -> list:
        """
        구글 뉴스 RSS 검색
        - keyword: 검색어
        - days: 최근 며칠 기사까지 수집할지
        """
        try:
            query = urllib.parse.quote(f"{keyword} when:{days}d")
            url = f"{self.BASE_URL}?q={query}&hl=ko&gl=KR&ceid=KR:ko"

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0"}
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")

            return self._parse_rss(raw, keyword)

        except Exception as e:
            print(f"  [구글RSS 오류] {keyword}: {e}")
            return []

    def _parse_rss(self, xml_text: str, keyword: str) -> list:
        """RSS XML 파싱"""
        articles = []
        cutoff = datetime.now() - timedelta(days=3)

        try:
            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                return []

            for item in channel.findall("item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                pub_date_str = item.findtext("pubDate", "")
                description = item.findtext("description", "")

                # 날짜 파싱
                pub_datetime = self._parse_date(pub_date_str)
                if pub_datetime and pub_datetime < cutoff:
                    continue

                # 구글 뉴스 링크에서 실제 URL 추출
                real_link = self._extract_real_link(link, description)

                # 언론사 추출
                source = self._extract_source(title, description)

                # 제목에서 언론사 제거 (구글RSS는 제목에 언론사가 붙음)
                clean_title = self._clean_title(title)

                articles.append({
                    "title": clean_title,
                    "description": self._clean_html(description),
                    "link": real_link or link,
                    "originallink": real_link or link,
                    "pubDate": pub_date_str,
                    "pub_datetime": pub_datetime,
                    "keyword": keyword,
                    "source": source,
                    "collector": "google_rss",
                })

        except ET.ParseError as e:
            print(f"  [RSS 파싱 오류] {e}")

        return articles

    def _parse_date(self, date_str: str):
        """날짜 파싱"""
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str).replace(tzinfo=None)
        except Exception:
            return None

    def _extract_real_link(self, link: str, description: str) -> str:
        """구글 RSS 링크에서 실제 기사 URL 추출"""
        # description에서 href 추출 시도
        match = re.search(r'href="([^"]+)"', description)
        if match:
            url = match.group(1)
            if url.startswith("http") and "google.com" not in url:
                return url
        return link

    def _extract_source(self, title: str, description: str) -> str:
        """구글 뉴스 RSS에서 언론사명 추출 (제목 끝에 붙어있음)"""
        # 형식: "기사 제목 - 언론사명"
        if " - " in title:
            return title.split(" - ")[-1].strip()
        return "알 수 없음"

    def _clean_title(self, title: str) -> str:
        """제목에서 언론사 부분 제거"""
        if " - " in title:
            return " - ".join(title.split(" - ")[:-1]).strip()
        return title.strip()

    def _clean_html(self, text: str) -> str:
        """HTML 태그 제거"""
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        return text.strip()
