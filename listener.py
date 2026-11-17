"""
텔레그램 명령 수신 (GitHub Actions에서 약 13분씩 이어서 실행)
- 사무관이 브리핑·긴급 알림에 "1, 2 대응"이라고 보내면 해당 번호 기사로 사전보고 초안을 써서 답장
- 답장(reply)으로 보내면 그 메시지의 번호, 그냥 보내면 가장 최근 메시지의 번호로 찾음
- 등록된 채팅(TELEGRAM_CHAT_ID)에서 온 메시지만 처리
"""

import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

from prereport import write_prereport
from telegram_sender import TelegramSender

HISTORY_FILE = "sent_history.json"
LISTEN_SECONDS = int(os.environ.get("LISTEN_MINUTES", "13")) * 60
MAX_AGE_SECONDS = 6 * 3600  # 리스너가 꺼져 있던 사이 온 명령은 6시간 안의 것만 처리

HELP = ("사용법: 브리핑·긴급 알림의 기사 번호와 함께 '대응'이라고 보내세요.\n"
        "예) 1, 2 대응  /  3번 대응\n"
        "알림 메시지에 답장으로 보내면 그 메시지의 번호로, 그냥 보내면 가장 최근 알림의 번호로 찾습니다.")


def api(token: str, method: str, params: dict, timeout: int = 70) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_lists() -> list:
    # 리스너가 도는 사이 브리핑이 새 목록을 커밋했을 수 있으므로 최신본을 받음
    subprocess.run(["git", "pull", "-q", "--ff-only"], check=False)
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f).get("lists", [])
    except Exception:
        return []


def find_list(lists: list, reply_to_id):
    if reply_to_id:
        for entry in reversed(lists):
            if reply_to_id in entry.get("message_ids", []):
                return entry
    return lists[-1] if lists else None


def parse_numbers(text: str) -> list:
    nums = [int(n) for n in re.findall(r"\d+", text)]
    return list(dict.fromkeys(n for n in nums if 0 < n < 100))


def handle(sender: TelegramSender, gemini_key: str, msg: dict):
    text = (msg.get("text") or "").strip()
    sender.reply_to = msg.get("message_id")
    if "대응" not in text or not parse_numbers(text):
        sender.send_message(HELP)
        return
    reply_to_id = (msg.get("reply_to_message") or {}).get("message_id")
    entry = find_list(load_lists(), reply_to_id)
    if not entry:
        sender.send_message("최근 알림 목록을 찾지 못했습니다. 다음 브리핑 뒤에 다시 보내 주세요.")
        return
    items = entry["items"]
    nums = parse_numbers(text)
    bad = [n for n in nums if n > len(items)]
    nums = [n for n in nums if n <= len(items)]
    if bad:
        sender.send_message(f"{entry['sent_at']} 알림에는 {len(items)}번까지만 있습니다. ({', '.join(map(str, bad))}번 제외)")
    if not nums:
        return
    sender.send_message(f"{entry['sent_at']} 알림의 {', '.join(f'{n}번' for n in nums)} 사전보고 초안 작성 중입니다. (건당 1분 안팎)")
    for n in nums:
        item = items[n - 1]
        try:
            draft = write_prereport(gemini_key, item)
            sender.send_message(f"[{n}번 사전보고 초안]\n\n{draft}")
        except Exception as e:
            print(f"  [초안 실패] {n}번: {e}")
            sender.send_message(
                f"[{n}번] 초안 자동 작성에 실패했습니다. Claude에 아래 링크를 붙이고 '대응 필요'라고 해 주세요.\n"
                f"{item.get('title', '')}\n{(item.get('links') or [''])[0]}")


def main():
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    gemini_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    sender = TelegramSender(token, chat_id)
    deadline = time.time() + LISTEN_SECONDS
    offset = None
    print(f"텔레그램 명령 대기 시작 ({LISTEN_SECONDS // 60}분)")
    while time.time() < deadline:
        wait = int(max(1, min(50, deadline - time.time())))
        params = {"timeout": wait, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            params["offset"] = offset
        try:
            res = api(token, "getUpdates", params, timeout=wait + 20)
        except Exception as e:
            print(f"  [getUpdates 오류] {e}")
            time.sleep(5)
            continue
        for upd in res.get("result", []):
            offset = upd["update_id"] + 1  # 다음 호출에서 이 메시지는 처리된 것으로 지워짐
            msg = upd.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != chat_id:
                continue  # 등록된 채팅이 아니면 무시
            if time.time() - msg.get("date", 0) > MAX_AGE_SECONDS:
                continue
            print(f"  명령 수신: {(msg.get('text') or '')[:30]}")
            try:
                handle(sender, gemini_key, msg)
            except Exception as e:
                print(f"  [처리 오류] {e}")
            sender.reply_to = None
    # 마지막으로 받은 메시지까지 처리 완료로 표시
    if offset is not None:
        try:
            api(token, "getUpdates", {"offset": offset, "timeout": 0}, timeout=20)
        except Exception:
            pass
    print("대기 종료")


if __name__ == "__main__":
    main()
