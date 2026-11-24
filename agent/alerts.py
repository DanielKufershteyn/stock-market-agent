"""Alert delivery. Discord webhook is the main channel; Telegram still works if you set its secrets."""
import os
import time

import requests


def _discord(text):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return None
    body = {"content": text[:1990], "flags": 4, "allowed_mentions": {"parse": []}}   # flags 4 = no link previews
    try:
        for _ in range(2):
            r = requests.post(url, json=body, timeout=15)
            if r.status_code == 429:                       # Discord rate limit: wait and retry once
                time.sleep(min(10.0, float(r.json().get("retry_after", 1))))
                continue
            if not r.ok:
                print("[discord] HTTP", r.status_code, r.text[:150])
            return r.ok
    except Exception as e:
        print("[discord] error:", e)
    return False


def _telegram(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return None
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}, timeout=20)
        return r.ok
    except Exception as e:
        print("[telegram] error:", e)
        return False


def send(text):
    results = [_discord(text), _telegram(text)]
    if all(r is None for r in results):
        print("[no alert channel configured]\n" + text + "\n")
        return False
    return any(bool(r) for r in results)


send_telegram = send      # old name, kept so nothing breaks
