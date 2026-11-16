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
        # Secrets에 붙여 넣을 때 섞여 들어간 줄바꿈·공백 제거
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()

    def send_message(self, text: str, silent: bool = False, html: bool = False) -> bool:
        """
        텔레그램 메시지 전송 (plain text, 4096자 초과 시 자동 분할)
        silent=True면 알림음 없이 전송
        """
        # 특수문자 정리
        text = self._clean_text(text)

        chunks = self._split_message(text, max_length=4000)

        ok = True
        for chunk in chunks:
            ok = self._send_chunk(chunk, silent, html) and ok
            time.sleep(0.5)

        return ok

    def _send_chunk(self, text: str, silent: bool = False, html: bool = False) -> bool:
        """단일 메시지 청크 전송. html=True면 제목에 링크를 거는 HTML 모드, 실패하면 일반 글자로 다시 보냄"""
        if html:
            if self._post(text, silent, parse_mode="HTML", preview=False):
                return True
            import re, html as _h
            plain = re.sub(r'<a href="([^"]*)">(.*?)</a>', lambda m: f"{m.group(2)}\n   {_h.unescape(m.group(1))}", text)
            plain = _h.unescape(re.sub(r"<[^>]+>", "", plain))
            print("  [텔레그램] HTML 전송 실패 → 일반 글자로 재전송")
            return self._post(plain, silent)
        return self._post(text, silent)

    def _post(self, text: str, silent: bool, parse_mode: str = "", preview: bool = True) -> bool:
        try:
            url = self.BASE_URL.format(token=self.token, method="sendMessage")

            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": not preview,
                "disable_notification": silent,
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
