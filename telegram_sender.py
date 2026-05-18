"""
텔레그램 봇 메시지 전송 모듈
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

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        텔레그램 메시지 전송
        - 4096자 초과 시 자동 분할
        """
        # 4096자 제한 분할
        chunks = self._split_message(text, max_length=4000)

        for chunk in chunks:
            success = self._send_chunk(chunk, parse_mode)
            if not success:
                # Markdown 실패 시 plain text 재시도
                self._send_chunk(chunk, parse_mode=None)
            time.sleep(0.5)  # 텔레그램 rate limit 방지

        return True

    def _send_chunk(self, text: str, parse_mode: str = "Markdown") -> bool:
        """단일 메시지 청크 전송"""
        try:
            url = self.BASE_URL.format(token=self.token, method="sendMessage")

            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": False,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

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

    def _split_message(self, text: str, max_length: int = 4000) -> list:
        """긴 메시지를 분할"""
        if len(text) <= max_length:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break
            # 줄바꿈 기준으로 분할
            split_pos = text.rfind("\n", 0, max_length)
            if split_pos == -1:
                split_pos = max_length
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")

        return chunks

    def send_file(self, file_path: str, caption: str = "") -> bool:
        """파일 전송 (향후 확장용)"""
        # 추후 일일 보고서 PDF 전송 등에 활용 가능
        pass
