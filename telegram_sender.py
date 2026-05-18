"""
텔레그램 봇 메시지 전송 모듈
- Markdown 제거하고 plain text로 전송 (특수문자 충돌 방지)
"""

import urllib.request
import urllib.parse
import json
import time


class TelegramSender:
    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send_message(self, text: str) -> bool:
        """
        텔레그램 메시지 전송 (plain text, 4096자 초과 시 자동 분할)
        """
        # 특수문자 정리
        text = self._clean_text(text)

        chunks = self._split_message(text, max_length=4000)

        for chunk in chunks:
            self._send_chunk(chunk)
            time.sleep(0.5)

        return True

    def _send_chunk(self, text: str) -> bool:
        """단일 메시지 청크 전송 (plain text)"""
        try:
            url = self.BASE_URL.format(token=self.token, method="sendMessage")

            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": False,
            }

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("ok", False)

        except Exception as e:
            print(f"  [텔레그램 오류] {e}")
            return False

    def _clean_text(self, text: str) -> str:
        """텔레그램 전송 전 텍스트 정리"""
        # JSON 코드블록 제거
        import re
        text = re.sub(r'```json.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        # 백틱 제거
        text = text.replace('`', '')
        # 연속 빈줄 정리
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def _split_message(self, text: str, max_length: int = 4000) -> list:
        """긴 메시지를 분할"""
        if len(text) <= max_length:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break
            split_pos = text.rfind("\n", 0, max_length)
            if split_pos == -1:
                split_pos = max_length
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")

        return chunks
