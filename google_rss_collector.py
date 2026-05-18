"""
구글 뉴스 RSS를 통한 뉴스 수집 모듈
- 네이버 API에서 못 잡는 지역지·전문지 커버
- 추가 API 키 불필요 (무료)
- 구글 RSS 암호화 링크 → 실제 기사 URL 변환 처리
"""

import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timedelta


class GoogleRSSCollector:

    BASE_URL = "https://news.google.com/rss/search"

    def __init__(self):
        pass

    def search(self, keyword: str, days: int = 3) -> list:
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

                # 실제 기사 URL 추출 (구글 암호화 링크 → 실제 URL)
                real_link = self._resolve_real_link(link, description)

                # 언론사 추출
                source = self._extract_source(title)

                # 제목 정리
                clean_title = self._clean_title(title)

                articles.append({
                    "title": clean_title,
                    "description": self._clean_html(description),
                    "link": real_link,
                    "originallink": real_link,
                    "pubDate": pub_date_str,
                    "pub_datetime": pub_datetime,
                    "keyword": keyword,
                    "source": source,
                    "collector": "google_rss",
                })

        except ET.ParseError as e:
            print(f"  [RSS 파싱 오류] {e}")

        return articles

    def _resolve_real_link(self, google_link: str, description: str) -> str:
        """
        구글 RSS 암호화 링크 → 실제 기사 URL 변환
        방법1: description HTML에서 href 추출
        방법2: 구글 링크 리다이렉트 따라가기
        """
        # 방법1: description에서 실제 URL 추출
        match = re.search(r'href="(https?://(?!news\.google\.com)[^"]+)"', description)
        if match:
            return match.group(1)

        # 방법2: 구글 링크 리다이렉트 따라가기
        if "news.google.com" in google_link:
            try:
                req = urllib.request.Request(
                    google_link,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                # 리다이렉트 따라가기
                with urllib.request.urlopen(req, timeout=5) as resp:
                    final_url = resp.geturl()
                    if "news.google.com" not in final_url:
                        return final_url
            except Exception:
                pass

        return google_link

    def _parse_date(self, date_str: str):
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str).replace(tzinfo=None)
        except Exception:
            return None

    def _extract_source(self, title: str) -> str:
        """구글 뉴스 RSS 제목 끝 언론사명 추출 (형식: 기사제목 - 언론사)"""
        if " - " in title:
            return title.split(" - ")[-1].strip()
        return "알 수 없음"

    def _clean_title(self, title: str) -> str:
        """제목에서 언론사 부분 제거"""
        if " - " in title:
            return " - ".join(title.split(" - ")[:-1]).strip()
        return title.strip()

    def _clean_html(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        return text.strip()
