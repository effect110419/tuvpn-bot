"""
TuVPN News Bot — автоматическая генерация постов для новостного канала.
Запускается по cron каждые 3 часа, присылает Максиму предложку поста в бота.

Зависимости: anthropic, feedparser, requests
Нужны ENV: BOT_TOKEN, ANTHROPIC_API_KEY
"""

import os
import sys
import json
import random
import logging
import hashlib
import requests
import feedparser
from datetime import datetime, timedelta, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("news_bot")

# Загружаем .env вручную (не используем python-dotenv)
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

BOT_TOKEN        = os.environ["BOT_TOKEN"]
ANTHROPIC_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
SUPERADMIN_ID    = 784871620
SENT_CACHE_FILE  = "/tmp/tuvpn_news_sent.json"

# ── RSS-источники по теме IT/VPN/интернет-свободы ───────────────────────
RSS_FEEDS = [
    # Рунет-цензура и VPN
    ("https://www.rbc.ru/rss/technology_and_media/", "RBC Tech"),
    ("https://www.cnews.ru/inc/rss/news.xml", "CNews"),
    ("https://habr.com/ru/rss/hub/network_technologies/all/?fl=ru", "Habr Сети"),
    ("https://habr.com/ru/rss/hub/information_security/all/?fl=ru", "Habr Безопасность"),
    ("https://habr.com/ru/rss/hub/vpn/all/?fl=ru", "Habr VPN"),
    ("https://meduza.io/rss/news", "Meduza"),
    ("https://www.securitylab.ru/rss/", "SecurityLab"),
    # Мировые IT
    ("https://feeds.arstechnica.com/arstechnica/technology-lab", "Ars Technica"),
    ("https://techcrunch.com/feed/", "TechCrunch"),
    ("https://www.theverge.com/rss/index.xml", "The Verge"),
    ("https://wired.com/feed/rss", "Wired"),
]

# Ключевые слова для фильтрации релевантных новостей
KEYWORDS = [
    "vpn", "vpn", "роскомнадзор", "блокировк", "цензур",
    "telegram", "интернет", "трафик", "dns", "proxy", "прокси",
    "обход", "фильтр", "ограничен", "sanction", "freedom",
    "privacy", "безопасност", "encrypt", "шифрован",
    "cloudflare", "tor ", "i2p", "wireguard", "xray", "v2ray",
    "антипират", "пиратств", "copyright",
    "2024", "2025", "2026",
]


def load_sent_cache() -> set:
    try:
        with open(SENT_CACHE_FILE) as f:
            data = json.load(f)
        # Очищаем записи старше 7 дней
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return {k for k, v in data.items() if v > cutoff}
    except Exception:
        return set()


def save_sent_cache(cache: set):
    now = datetime.now(timezone.utc).isoformat()
    try:
        old = {}
        try:
            with open(SENT_CACHE_FILE) as f:
                old = json.load(f)
        except Exception:
            pass
        old.update({k: now for k in cache})
        with open(SENT_CACHE_FILE, "w") as f:
            json.dump(old, f)
    except Exception as e:
        log.warning(f"Не удалось сохранить кэш: {e}")


def fetch_news() -> list[dict]:
    """Парсит RSS-ленты и возвращает список свежих новостей."""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    sent = load_sent_cache()

    for url, source in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:20]:
                title = (entry.get("title") or "").strip()
                summary = (entry.get("summary") or entry.get("description") or "")[:500]
                link = entry.get("link") or ""

                # Пропускаем уже отправленные
                uid = hashlib.md5(link.encode()).hexdigest()[:12]
                if uid in sent:
                    continue

                # Проверяем дату публикации
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue

                # Фильтр по ключевым словам
                text = (title + " " + summary).lower()
                score = sum(1 for kw in KEYWORDS if kw in text)
                if score == 0:
                    continue

                articles.append({
                    "uid": uid,
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "source": source,
                    "score": score,
                    "pub": pub_dt.isoformat() if pub else "",
                })
        except Exception as e:
            log.warning(f"Ошибка парсинга {source}: {e}")

    # Сортируем по релевантности, берём топ-10
    articles.sort(key=lambda x: x["score"], reverse=True)
    return articles[:10]


def generate_post(article: dict) -> str:
    """Генерирует готовый Telegram-пост через Claude API."""
    if not ANTHROPIC_KEY:
        # Запасной вариант без API — форматируем напрямую
        return _format_fallback(article)

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    prompt = f"""Ты — SMM-редактор новостного Telegram-канала о VPN и цифровой свободе в России.
Аудитория: обычные пользователи, которые используют VPN для обхода блокировок.
Тон: живой, понятный, без корпоративного официоза. Иногда с лёгкой иронией.

Напиши пост для Telegram на основе этой новости:
Заголовок: {article['title']}
Источник: {article['source']}
Содержание: {article['summary']}

Требования к посту:
- Длина: 3-5 абзацев, 150-250 слов
- Начни с цепляющего заголовка с эмодзи
- Объясни суть простыми словами
- Добавь практический вывод — что это значит для пользователей VPN
- В конце 3-5 тематических хэштегов (#VPN #интернет #блокировки и подобные)
- Никаких ссылок в теле поста — только текст

Пиши только сам пост, без пояснений."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        log.error(f"Claude API error: {e}")
        return _format_fallback(article)


def _format_fallback(article: dict) -> str:
    """Простое форматирование без AI, когда нет ключа."""
    return (
        f"📰 <b>{article['title']}</b>\n\n"
        f"{article['summary'][:300]}...\n\n"
        f"🔗 <a href=\"{article['link']}\">Читать полностью</a>\n\n"
        f"<i>Источник: {article['source']}</i>\n\n"
        f"#VPN #интернет #новости"
    )


def find_image_url(article: dict) -> str | None:
    """Ищет релевантное изображение через Unsplash API (если настроен) или возвращает None."""
    unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not unsplash_key:
        return None
    try:
        # Формируем поисковый запрос на английском
        queries = ["internet security", "vpn privacy", "digital freedom", "cybersecurity", "network"]
        query = random.choice(queries)
        r = requests.get(
            "https://api.unsplash.com/photos/random",
            params={"query": query, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {unsplash_key}"},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("urls", {}).get("regular")
    except Exception as e:
        log.warning(f"Unsplash error: {e}")
    return None


def send_to_admin(text: str, image_url: str | None, article: dict):
    """Отправляет пост Максиму в Telegram."""
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    # Сначала отправляем метаинформацию
    header = (
        f"🗞 <b>Предложка поста</b> · {datetime.now().strftime('%H:%M %d.%m')}\n"
        f"📡 Источник: {article['source']}\n"
        f"🔗 <a href=\"{article['link']}\">Оригинал</a>\n"
        f"{'─'*30}\n\n"
    )
    full_text = header + text

    try:
        if image_url:
            # Отправляем с картинкой
            r = requests.post(f"{base}/sendPhoto", json={
                "chat_id": SUPERADMIN_ID,
                "photo": image_url,
                "caption": full_text[:1024],
                "parse_mode": "HTML",
            }, timeout=15)
            if r.status_code != 200:
                # Картинка не прошла — шлём без неё
                raise Exception(f"photo failed: {r.text[:100]}")
        else:
            raise Exception("no image")
    except Exception:
        # Отправляем только текст
        requests.post(f"{base}/sendMessage", json={
            "chat_id": SUPERADMIN_ID,
            "text": full_text[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)


def main():
    log.info("Запускаю сбор новостей...")

    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан")
        sys.exit(1)

    articles = fetch_news()
    if not articles:
        log.info("Нет новых релевантных новостей")
        return

    # Берём самую релевантную (или случайную из топ-3 для разнообразия)
    top = articles[:min(3, len(articles))]
    article = random.choice(top)

    log.info(f"Выбрана новость: {article['title'][:80]} (score={article['score']})")

    post_text = generate_post(article)
    image_url = find_image_url(article)

    send_to_admin(post_text, image_url, article)

    # Отмечаем как отправленную
    cache = load_sent_cache()
    cache.add(article["uid"])
    save_sent_cache(cache)

    log.info("Готово — пост отправлен Максиму")


if __name__ == "__main__":
    main()
