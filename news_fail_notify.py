# -*- coding: utf-8 -*-
"""
Запасное уведомление о крахе генерации поста.
Запускается systemd через OnFailure= у tuvpn-news.service — то есть только когда
news_bot.py завершился с ошибкой И сам не смог отправить уведомление
(краш до отправки, OOM, отвал сети в момент уведомления).

Шлёт суперадмину последние строки журнала и кнопку «Попробовать снова».
"""

import os
import html
import subprocess

import requests


def _load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SUPERADMIN_ID = 784871620


def main():
    if not BOT_TOKEN:
        return
    try:
        tail = subprocess.run(
            ["journalctl", "-u", "tuvpn-news", "-n", "8", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()[-700:]
    except Exception:
        tail = "(журнал недоступен)"

    kb = {"inline_keyboard": [[{"text": "🔁 Попробовать снова", "callback_data": "news_retry"}]]}
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
        "chat_id": SUPERADMIN_ID,
        "text": ("⚠️ <b>Генерация поста упала</b>\n\n"
                 "Процесс завершился с ошибкой и не смог отчитаться сам. "
                 "Последние строки журнала:\n"
                 f"<pre>{html.escape(tail)}</pre>"),
        "parse_mode": "HTML",
        "reply_markup": kb,
        "disable_web_page_preview": True,
    }, timeout=15)


if __name__ == "__main__":
    main()
