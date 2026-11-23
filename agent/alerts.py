import os

import requests


def send_telegram(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("[telegram not configured]\n" + text + "\n")
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True},
                          timeout=20)
        return r.ok
    except Exception as e:
        print("[telegram] error:", e)
        return False
