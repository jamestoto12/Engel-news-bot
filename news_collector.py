"""
네이버 뉴스 API를 통한 뉴스 수집 모듈
"""

import urllib.request
import urllib.parse
import json
import re
from datetime import datetime, timedelta


class NewsCollector:
    BASE_URL = "https://openapi.naver.com/v1/search/news.json"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def search(self, keyword: str, display: int = 10, sort: str = "date") -> list:
        """
        네이버 뉴스 검색
        - keyword: 검색어
        - display: 결과 수 (최대 100)
        - sort: date(최신순) / sim(관련도순)
        """
        try:
            query = urllib.parse.quote(keyword)
            url = f"{self.BASE_URL}?query={query}&display={display}&sort={sort}"

            request = urllib.request.Request(url)
            request.add_header("X-Naver-Client-Id", self.client_id)
            request.add_header("X-Naver-Client-Secret", self.client_secret)

            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw)

            articles = []
            cutoff = datetime.now() - timedelta(hours=24)  # 최근 24시간

            for item in data.get("items", []):
                # 날짜 파싱
                pub_date = self._parse_date(item.get("pubDate", ""))
                if pub_date and pub_date < cutoff:
                    continue  # 24시간 이전 기사 제외

                articles.append({
                    "title": self._clean_html(item.get("title", "")),
                    "description": self._clean_html(item.get("description", "")),
                    "link": item.get("link", ""),
                    "originallink": item.get("originallink", ""),
                    "pubDate": item.get("pubDate", ""),
                    "pub_datetime": pub_date,
                    "keyword": keyword,
                    "source": self._extract_source(item.get("originallink", "")),
                })

            return articles

        except Exception as e:
            print(f"  [오류] {keyword} 수집 실패: {e}")
            return []

    def _parse_date(self, date_str: str):
        """날짜 문자열 파싱"""
        try:
            # RFC 822 형식: "Mon, 21 Apr 2025 06:00:00 +0900"
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(date_str).replace(tzinfo=None)
        except Exception:
            return None

    def _clean_html(self, text: str) -> str:
        """HTML 태그 제거"""
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        return text.strip()

    def _extract_source(self, url: str) -> str:
        """URL에서 언론사명 추출"""
        source_map = {
            "yonhapnews": "연합뉴스", "yna.co.kr": "연합뉴스",
            "chosun": "조선일보", "donga": "동아일보",
            "joongang": "중앙일보", "hani.co.kr": "한겨레",
            "khan.co.kr": "경향신문", "ohmynews": "오마이뉴스",
            "newsis": "뉴시스", "newspim": "뉴스핌",
            "heraldcorp": "헤럴드경제", "mt.co.kr": "머니투데이",
            "fnnews": "파이낸셜뉴스", "sedaily": "서울경제",
            "mk.co.kr": "매일경제", "hankyung": "한국경제",
            "kbs.co.kr": "KBS", "mbc.co.kr": "MBC",
            "sbs.co.kr": "SBS", "jtbc": "JTBC",
            "ytn.co.kr": "YTN", "fisheco": "수산경제신문",
            "nffc": "수협", "mof.go.kr": "해양수산부",
            "moj.go.kr": "법무부",
        }
        url_lower = url.lower()
        for key, name in source_map.items():
            if key in url_lower:
                return name
        # 도메인 추출 fallback
        try:
            domain = url.split("/")[2].replace("www.", "")
            return domain
        except Exception:
            return "알 수 없음"
