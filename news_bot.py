"""
TuVPN News Bot — автоматическая генерация постов для новостного канала.
Запускается по cron каждые 3 часа, присылает Максиму предложку поста в бота.

Зависимости: anthropic, feedparser, requests
Нужны ENV: BOT_TOKEN, ANTHROPIC_API_KEY (опционально)
"""

import os
import sys
import json
import html
import random
import logging
import hashlib
import re
import requests
import feedparser
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("news_bot")


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

BOT_TOKEN        = os.environ.get("BOT_TOKEN", "")
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
SUPERADMIN_ID    = 784871620
SENT_CACHE_FILE  = "/tmp/tuvpn_news_sent.json"

# ── RSS-источники по теме IT/VPN/интернет-свободы ───────────────────────
RSS_FEEDS = [
    ("https://www.cnews.ru/inc/rss/news.xml",                          "CNews"),
    ("https://habr.com/ru/rss/hub/network_technologies/all/?fl=ru",    "Habr Сети"),
    ("https://habr.com/ru/rss/hub/information_security/all/?fl=ru",    "Habr Безопасность"),
    ("https://habr.com/ru/rss/hub/vpn/all/?fl=ru",                     "Habr VPN"),
    ("https://habr.com/ru/rss/hub/linux/all/?fl=ru",                   "Habr Linux"),
    ("https://www.securitylab.ru/rss/",                                "SecurityLab"),
    ("https://feeds.arstechnica.com/arstechnica/technology-lab",       "Ars Technica"),
    ("https://techcrunch.com/feed/",                                   "TechCrunch"),
    ("https://www.theverge.com/rss/index.xml",                        "The Verge"),
]

# Ключевые слова — минимум 2 должны совпасть, чтобы статья прошла
KEYWORDS = [
    "vpn", "vpn", "впн", "роскомнадзор", "рунет",
    "блокировк", "разблокировк", "цензур", "обход",
    "telegram", "телеграм",
    "cloudflare", "tor", "wireguard", "xray", "v2ray", "shadowsocks",
    "proxy", "прокси", "тунн",
    "dns", "dpi", "deep packet", "fсi", "сорм",
    "privacy", "приватност", "анонимност",
    "encrypt", "шифрован", "tls", "ssl",
    "интернет-свобод", "свобод.*интернет",
    "zero-day", "уязвимост", "хакер", "кибербезопасност", "взлом",
    "утечк.*данных", "данных.*утечк",
    "санкц", "ограничен.*сеть", "сеть.*ограничен",
]

# Если встречается хотя бы одно из этих — точно берём
STRONG_KEYWORDS = [
    "vpn", "впн", "роскомнадзор", "рунет", "блокировк",
    "wireguard", "xray", "shadowsocks", "v2ray",
    "dpi", "роскомнадзор", "ркн",
]


def strip_html(text: str) -> str:
    """Убирает HTML-теги из текста."""
    return re.sub(r"<[^>]+>", "", text or "").strip()


def load_sent_cache() -> set:
    try:
        with open(SENT_CACHE_FILE) as f:
            data = json.load(f)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return {k for k, v in data.items() if v > cutoff}
    except Exception:
        return set()


def save_sent_id(uid: str):
    try:
        old = {}
        try:
            with open(SENT_CACHE_FILE) as f:
                old = json.load(f)
        except Exception:
            pass
        old[uid] = datetime.now(timezone.utc).isoformat()
        with open(SENT_CACHE_FILE, "w") as f:
            json.dump(old, f)
    except Exception as e:
        log.warning(f"Не удалось сохранить кэш: {e}")


def fetch_news() -> list[dict]:
    """Парсит RSS-ленты и возвращает список свежих релевантных новостей."""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    sent = load_sent_cache()

    for url, source in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in (feed.entries or [])[:25]:
                title = strip_html(entry.get("title") or "").strip()
                summary = strip_html(entry.get("summary") or entry.get("description") or "")[:600]
                link = (entry.get("link") or "").strip()

                if not title or not link:
                    continue

                uid = hashlib.md5(link.encode()).hexdigest()[:12]
                if uid in sent:
                    continue

                # Проверяем дату публикации
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_dt = None
                if pub:
                    try:
                        pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                        if pub_dt < cutoff:
                            continue
                    except Exception:
                        pass

                text_lower = (title + " " + summary).lower()

                # Считаем совпадения
                strong = sum(1 for kw in STRONG_KEYWORDS if kw in text_lower)
                weak   = sum(1 for kw in KEYWORDS if re.search(kw, text_lower))
                score  = strong * 3 + weak

                # Минимальный порог — хотя бы одно сильное слово ИЛИ три слабых
                if strong == 0 and weak < 3:
                    continue

                articles.append({
                    "uid": uid,
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "source": source,
                    "score": score,
                    "pub": pub_dt.isoformat() if pub_dt else "",
                })
        except Exception as e:
            log.warning(f"Ошибка парсинга {source}: {e}")

    articles.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"Найдено подходящих статей: {len(articles)}")
    return articles[:10]


def generate_post(article: dict) -> str:
    """Генерирует готовый Telegram-пост через Claude API."""
    if not ANTHROPIC_KEY:
        return _format_fallback(article)

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""Ты — SMM-редактор Telegram-канала о VPN и цифровой свободе в России.
Аудитория: обычные люди, которые используют VPN чтобы заходить в Instagram, смотреть YouTube без тормозов, читать заблокированные сайты.
Тон: живой, понятный, иногда с лёгкой иронией. Без корпоративного официоза.

Напиши пост на основе этой новости:
Заголовок: {article['title']}
Источник: {article['source']}
Содержание: {article['summary']}

Требования:
- 150-220 слов
- Начни с яркого заголовка + эмодзи (не "📰")
- Объясни суть простым языком — что произошло и почему это важно
- Добавь конкретный вывод для пользователя VPN ("что мне с этого?")
- В конце 3-4 хэштега (#VPN #интернет #блокировки #безопасность)
- Только текст, без ссылок внутри поста

Верни только сам пост."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.error(f"Claude API error: {e}")
        return _format_fallback(article)


def _format_fallback(article: dict) -> str:
    """Простое форматирование без AI."""
    safe_title   = html.escape(article["title"])
    safe_summary = html.escape(article["summary"][:400])
    safe_source  = html.escape(article["source"])
    return (
        f"📡 <b>{safe_title}</b>\n\n"
        f"{safe_summary}...\n\n"
        f"<i>Источник: {safe_source}</i>\n\n"
        f"#VPN #интернет #новости #безопасность"
    )


def send_to_admin(text: str, article: dict):
    """Отправляет предложку поста Максиму в Telegram."""
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан — отправка невозможна")
        return

    base = f"https://api.telegram.org/bot{BOT_TOKEN}"
    safe_source = html.escape(article["source"])
    safe_link   = article["link"]
    ts = datetime.now().strftime("%H:%M %d.%m")

    header = (
        f"🗞 <b>Предложка поста</b> · {ts}\n"
        f"📡 {safe_source} · "
        f'<a href="{safe_link}">оригинал</a>\n'
        f"{'─' * 28}\n\n"
    )
    full_text = (header + text)[:4096]

    r = requests.post(f"{base}/sendMessage", json={
        "chat_id": SUPERADMIN_ID,
        "text": full_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=15)

    resp = r.json()
    if resp.get("ok"):
        log.info(f"Пост отправлен, message_id={resp['result']['message_id']}")
    else:
        log.error(f"Telegram API error: {resp.get('description')} (code {resp.get('error_code')})")
        # Пробуем ещё раз без HTML (plain text)
        plain = re.sub(r"<[^>]+>", "", full_text)
        r2 = requests.post(f"{base}/sendMessage", json={
            "chat_id": SUPERADMIN_ID,
            "text": plain[:4096],
            "disable_web_page_preview": True,
        }, timeout=15)
        resp2 = r2.json()
        if resp2.get("ok"):
            log.info("Отправлено как plain text (fallback)")
        else:
            log.error(f"Plain text тоже не прошёл: {resp2.get('description')}")


def main():
    log.info("Запускаю сбор новостей...")

    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан")
        sys.exit(1)

    articles = fetch_news()

    if not articles:
        log.info("Нет новых релевантных новостей — пропускаем")
        return

    # Берём случайную из топ-3 для разнообразия
    top = articles[:min(3, len(articles))]
    article = random.choice(top)
    log.info(f"Выбрана: [{article['source']}] {article['title'][:80]} (score={article['score']})")

    post_text = generate_post(article)
    send_to_admin(post_text, article)
    save_sent_id(article["uid"])
    log.info("Готово")


if __name__ == "__main__":
    main()
