# -*- coding: utf-8 -*-
"""
TuVPN News Bot — контент-машина канала @tuvpn_news.

Каждый запуск (systemd-таймер, 5 раз в день):
 1. Берёт следующую тему из контент-плана (news_topics.py, ротация без повторов)
    или — если в RSS есть по-настоящему горячая профильная новость — новость.
 2. Пишет пост через Claude (маркетинговый промпт, факты о продукте, ≤900 символов).
 3. Рендерит футуристичную обложку под заголовок (news_cover.py, без внешних API).
 4. Шлёт Максиму предложку: фото + готовый caption + кнопки
    «✅ В канал» (публикация через copyMessage, хендлер в bot.py) и «❌ Пропустить».

CLI: --topic <id>  — принудительно конкретная тема
     --plan        — игнорировать горячие новости, только контент-план
     --dry         — не отправлять и не менять состояние: пост в stdout, обложка в /tmp/news_dry.png
Зависимости: anthropic, feedparser, requests, pillow
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

from news_topics import TOPICS, NEWS_META
from news_cover import generate_cover

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

BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = os.environ.get("ANTHROPIC_BASE_URL", "")
SUPERADMIN_ID = 784871620
STATE_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news_state.json")

MODEL = "claude-sonnet-5"          # тексты — маркетинг, экономить тут нельзя
HOT_NEWS_MIN_SCORE = 12            # порог «горячей» новости, перебивающей контент-план
HOT_NEWS_PROBABILITY = 0.35        # даже горячую берём не всегда — план важнее

# ── КОНТЕКСТ О ПРОДУКТЕ (только чтобы модель не наврала, НЕ для рекламы) ──
PRODUCT_FACTS = """
Канал ведёт команда VPN-сервиса TuVPN (протокол VLESS + Reality, раздельная маршрутизация:
российские сервисы напрямую, заблокированные — через туннель). Эти факты нужны только
для точности, если тема поста прямо касается устройства современных VPN.
Цены, тарифы и условия сервиса в постах НЕ упоминаются никогда.
"""

BRAND_VOICE = """
Редполитика канала:
- Это техноблог про интернет, приватность, цифровую жизнь и технологии — НЕ рекламная витрина.
  Читатели уже клиенты; им должно быть ИНТЕРЕСНО, а не «продано».
- Голос: любопытный технарь-журналист. Объясняет просто, находит неожиданные факты,
  не умничает, не пугает, не заискивает.
- Конкретика вместо воды: цифры, даты, названия, примеры из жизни, вау-факты.
- Лёгкая ирония допустима, кликбейт-истерика — нет.
- TuVPN упоминать МАКСИМУМ одним нейтральным предложением и только если это органично теме
  (например, пост про протоколы может вскользь заметить «мы в TuVPN используем Reality как раз
  поэтому»). В большинстве постов TuVPN не упоминается вовсе — и это нормально.
- Никогда не обещаем «анонимность от спецслужб», не даём юридических советов,
  не призываем нарушать закон.
- Instagram и Meta упоминаем со звёздочкой: Instagram* (*запрещён в РФ).
"""

# ── RSS для контекста и горячих новостей ─────────────────────────────
RSS_FEEDS = [
    ("https://www.cnews.ru/inc/rss/news.xml",                       "CNews"),
    ("https://habr.com/ru/rss/hub/network_technologies/all/?fl=ru", "Habr Сети"),
    ("https://habr.com/ru/rss/hub/information_security/all/?fl=ru", "Habr Безопасность"),
    ("https://www.securitylab.ru/rss/",                             "SecurityLab"),
]

STRONG_KEYWORDS = [
    "vpn", "впн", "роскомнадзор", "ркн", "рунет", "блокировк", "замедлен",
    "wireguard", "xray", "shadowsocks", "v2ray", "dpi", "тспу", "цензур",
]
WEAK_KEYWORDS = [
    "telegram", "телеграм", "youtube", "ютуб", "прокси", "tor", "dns",
    "приватност", "анонимност", "шифрован", "утечк", "слежк", "провайдер",
]


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


# ── состояние (ротация тем + кэш новостей) ───────────────────────────

def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
    except Exception as e:
        log.warning(f"Не удалось сохранить состояние: {e}")


def next_topic(state: dict) -> dict:
    """Следующая тема цикла. Цикл — перемешанный список id, без повторов до конца."""
    ids = [t["id"] for t in TOPICS]
    cycle = [i for i in state.get("cycle", []) if i in ids]
    if not cycle:
        cycle = ids[:]
        random.shuffle(cycle)
        log.info("Контент-план: новый цикл из %d тем", len(cycle))
    topic_id = cycle.pop(0)
    state["cycle"] = cycle
    return next(t for t in TOPICS if t["id"] == topic_id)


# ── новости ──────────────────────────────────────────────────────────

def fetch_news(state: dict) -> list:
    """Свежие релевантные статьи из RSS (для контекста и «горячего» режима)."""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    sent = state.get("sent_news", {})
    sent_cutoff = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    state["sent_news"] = {k: v for k, v in sent.items() if v > sent_cutoff}

    for url, source in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in (feed.entries or [])[:25]:
                title = strip_html(entry.get("title") or "")
                summary = strip_html(entry.get("summary") or entry.get("description") or "")[:500]
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                uid = hashlib.md5(link.encode()).hexdigest()[:12]
                if uid in state["sent_news"]:
                    continue
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                if pub:
                    try:
                        if datetime(*pub[:6], tzinfo=timezone.utc) < cutoff:
                            continue
                    except Exception:
                        pass
                text_lower = (title + " " + summary).lower()
                strong = sum(1 for kw in STRONG_KEYWORDS if kw in text_lower)
                weak = sum(1 for kw in WEAK_KEYWORDS if kw in text_lower)
                score = strong * 4 + weak
                if strong == 0:
                    continue
                articles.append({"uid": uid, "title": title, "summary": summary,
                                 "link": link, "source": source, "score": score})
        except Exception as e:
            log.warning(f"RSS {source}: {e}")

    articles.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"Релевантных новостей: {len(articles)}")
    return articles


# ── генерация текста ─────────────────────────────────────────────────

def _classify_api_error(e: Exception) -> str:
    """Переводит ошибку API в понятную человеку причину."""
    s = str(e)
    low = s.lower()
    if "401" in s or "authentication" in low or "invalid x-api-key" in low:
        return "ключ API отклонён (401) — проверь ANTHROPIC_API_KEY в .env"
    if "402" in s or "insufficient" in low or "balance" in low or "credit" in low or "quota" in low:
        return "закончились средства/кредиты на API (402) — пополни баланс proxyapi"
    if "429" in s or "rate limit" in low:
        return "превышен лимит запросов API (429) — попробуй чуть позже"
    if "529" in s or "overloaded" in low:
        return "API перегружен (529) — попробуй чуть позже"
    if "timed out" in low or "timeout" in low:
        return "таймаут запроса к API — сеть или API тормозят"
    if "connection" in low or "connect" in low:
        return "нет соединения с API"
    return f"ошибка API: {s[:200]}"


def _claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(
        api_key=ANTHROPIC_KEY,
        **({"base_url": ANTHROPIC_URL} if ANTHROPIC_URL else {}),
    )
    msg = client.messages.create(
        model=MODEL,
        # у sonnet-5 адаптивное мышление включено по умолчанию и тратит max_tokens —
        # даём запас, иначе текстовый блок приходит пустым
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    # ответ может содержать thinking-блоки — берём только текстовые
    parts = [b.text for b in msg.content if getattr(b, "type", "") == "text"]
    return "\n".join(parts).strip()


def _parse_json_answer(raw: str) -> dict | None:
    """Достаёт JSON из ответа модели (терпит ```json обёртки и сырые переносы строк)."""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        log.warning("В ответе нет JSON: %s", raw[:200])
        return None
    blob = m.group(0)
    for parser in (
        lambda s: json.loads(s),
        lambda s: json.loads(s, strict=False),  # разрешает \n внутри строк
    ):
        try:
            data = parser(blob)
            if data.get("post") and data.get("cover_title"):
                return data
        except Exception:
            continue
    log.warning("JSON не распарсился: %s", blob[:200])
    return None


def generate_content(topic: dict | None, article: dict | None, news_context: list) -> tuple:
    """Пост + заголовок/подзаголовок обложки.
    Возвращает (data, None) при успехе или (None, причина) при неудаче."""
    if not ANTHROPIC_KEY:
        return None, "ANTHROPIC_API_KEY не задан в .env — генерация невозможна"

    if topic:
        task = (f"Тема поста из контент-плана: «{topic['title']}»\n"
                f"Редакторский бриф (угол подачи): {topic['brief']}")
    else:
        task = (f"Пост по горячей новости:\n"
                f"Заголовок: {article['title']}\nИсточник: {article['source']}\n"
                f"Суть: {article['summary']}\n"
                f"Свяжи новость с пользой/риском для обычного пользователя интернета в РФ.")

    ctx = ""
    if news_context:
        ctx = "\nСвежий новостной фон (используй ТОЛЬКО если органично усиливает пост):\n" + \
              "\n".join(f"- {a['title']}" for a in news_context[:3])

    prompt = f"""Ты — редактор научно-популярного Telegram-канала о интернете, приватности и технологиях.
Твои посты собирают высокий охват, потому что их реально интересно читать: цепляют с первой строки, дают пользу или неожиданный факт — и не пахнут рекламой.

{BRAND_VOICE}
{PRODUCT_FACTS}
{task}
{ctx}

Напиши пост для Telegram-канала. Жёсткие требования:
1. Первая строка — хук: <b>жирный заголовок</b> с 1 эмодзи. Не повторяй тему дословно — переформулируй так, чтобы захотелось читать дальше (вопрос, цифра, неожиданный факт).
2. Тело: 2–4 коротких абзаца ИЛИ абзац + маркированный список (маркер «—» или эмодзи). Каждое предложение несёт факт, пользу или наблюдение. Пустая строка между абзацами.
3. Конкретика обязательна: названия, цифры, даты, примеры. Никаких «в современном мире» и «как известно».
4. Финал — сильный вывод, неожиданная мысль или практический совет одной строкой. ЗАПРЕЩЕНО: любые телеграм-хендлы (@-упоминания), ссылки-приглашения, призывы «подключайся/попробуй», упоминания цен, тарифов, пробных периодов и промо-акций.
5. Последняя строка: 2–3 тематических хэштега (без #TuVPN).
6. Форматирование: только HTML-теги <b> и <i>. БЕЗ markdown.
7. ДЛИНА ПОСТА: СТРОГО не более 850 символов включая теги и хэштеги (это caption к фото).
8. Не выдумывай факты, в которых не уверен; лучше меньше цифр, но точных.

Также придумай текст для обложки:
- cover_title: 3–6 слов, мощная выжимка поста (НЕ обязательно = заголовку поста). Одно ключевое слово оберни в *звёздочки* — оно будет подсвечено неоном. Без @-хендлов.
- cover_subtitle: до 7 слов, поясняющая строка без точки в конце, без @-хендлов и промо.

Ответь СТРОГО одним JSON-объектом без пояснений:
{{"cover_title": "...", "cover_subtitle": "...", "post": "..."}}"""

    last_reason = "неизвестная ошибка"
    for attempt in range(2):
        try:
            raw = _claude(prompt)
            data = _parse_json_answer(raw)
            if not data:
                last_reason = "модель вернула невалидный ответ (JSON не распарсился)"
                log.warning("Ответ не распарсился, попытка %d", attempt + 1)
                continue
            plain = re.sub(r"<[^>]+>", "", data["post"])
            if len(data["post"]) > 1000:
                last_reason = f"пост превысил лимит длины ({len(data['post'])} символов)"
                log.warning("Пост длиннее лимита (%d), попытка %d", len(data["post"]), attempt + 1)
                prompt += f"\n\nВНИМАНИЕ: прошлый вариант был {len(data['post'])} символов — СОКРАТИ до 850."
                continue
            log.info("Текст готов: %d символов, обложка: %s", len(plain), data["cover_title"])
            return data, None
        except Exception as e:
            last_reason = _classify_api_error(e)
            log.error(f"Claude API error: {e}")
    return None, last_reason


# ── уведомление о сбое ───────────────────────────────────────────────

def send_failure_notice(reason: str) -> bool:
    """Сообщает суперадмину о неудачной генерации, с кнопкой повтора."""
    try:
        kb = {"inline_keyboard": [[{"text": "🔁 Попробовать снова", "callback_data": "news_retry"}]]}
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
            "chat_id": SUPERADMIN_ID,
            "text": ("⚠️ <b>Не удалось сгенерировать пост</b>\n\n"
                     f"Причина: {html.escape(reason)[:800]}"),
            "parse_mode": "HTML",
            "reply_markup": kb,
            "disable_web_page_preview": True,
        }, timeout=15)
        ok = bool(r.json().get("ok"))
        log.info("Уведомление о сбое: %s", "доставлено" if ok else "НЕ доставлено")
        return ok
    except Exception as e:
        log.error(f"Не удалось отправить уведомление о сбое: {e}")
        return False


def _fail(reason: str):
    """Единая точка выхода при сбое: уведомляем и завершаемся.
    exit 0 — сбой обработан (уведомление доставлено), OnFailure не сработает.
    exit 1 — уведомить не удалось, systemd OnFailure отправит запасное уведомление."""
    log.error("Генерация не удалась: %s", reason)
    sys.exit(0 if send_failure_notice(reason) else 1)


# ── отправка предложки ───────────────────────────────────────────────

def send_proposal(data: dict, cover_png: bytes, meta_line: str) -> bool:
    """Фото + чистый caption (готов к публикации) + кнопки. Мета — отдельным сообщением."""
    base = f"https://api.telegram.org/bot{BOT_TOKEN}"

    # мета-сообщение (не попадёт в канал — публикуется только фото ниже)
    try:
        requests.post(f"{base}/sendMessage", json={
            "chat_id": SUPERADMIN_ID,
            "text": f"🗞 <b>Предложка для @tuvpn_news</b>\n{meta_line}",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
    except Exception:
        pass

    keyboard = {"inline_keyboard": [[
        {"text": "✅ В канал", "callback_data": "news_pub"},
        {"text": "❌ Пропустить", "callback_data": "news_skip"},
    ]]}
    caption = data["post"][:1024]
    try:
        r = requests.post(
            f"{base}/sendPhoto",
            data={"chat_id": SUPERADMIN_ID, "caption": caption, "parse_mode": "HTML",
                  "reply_markup": json.dumps(keyboard)},
            files={"photo": ("cover.png", cover_png, "image/png")},
            timeout=60,
        )
        resp = r.json()
        if resp.get("ok"):
            log.info("Предложка отправлена, message_id=%s", resp["result"]["message_id"])
            return True
        log.error("sendPhoto: %s", resp.get("description"))
        # fallback: HTML мог не пройти — шлём без parse_mode
        r2 = requests.post(
            f"{base}/sendPhoto",
            data={"chat_id": SUPERADMIN_ID, "caption": re.sub(r"<[^>]+>", "", caption),
                  "reply_markup": json.dumps(keyboard)},
            files={"photo": ("cover.png", cover_png, "image/png")},
            timeout=60,
        )
        return bool(r2.json().get("ok"))
    except Exception as e:
        log.error(f"sendPhoto exception: {e}")
        return False


# ── main ─────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN не задан")
        sys.exit(1)

    force_topic = None
    plan_only = "--plan" in sys.argv
    dry_run = "--dry" in sys.argv
    if "--topic" in sys.argv:
        try:
            force_topic = sys.argv[sys.argv.index("--topic") + 1]
        except IndexError:
            pass

    state = load_state()
    articles = fetch_news(state)

    topic, article = None, None
    if force_topic:
        topic = next((t for t in TOPICS if t["id"] == force_topic), None)
        if not topic:
            log.error("Тема %s не найдена. Доступные: %s", force_topic, ", ".join(t["id"] for t in TOPICS))
            sys.exit(1)
    elif (not plan_only and articles and articles[0]["score"] >= HOT_NEWS_MIN_SCORE
          and random.random() < HOT_NEWS_PROBABILITY):
        article = articles[0]
        log.info("Горячая новость перебила план: [%s] %s (score=%d)",
                 article["source"], article["title"][:70], article["score"])
    else:
        topic = next_topic(state)
        log.info("Тема из плана: %s", topic["title"])

    # новостной контекст — только темам, которым он полезен
    ctx = articles[:3] if (topic and topic.get("news_context")) else []
    data, gen_error = generate_content(topic, article, ctx)
    if not data:
        if dry_run:
            log.error("Генерация не удалась: %s", gen_error)
            sys.exit(1)
        _fail(gen_error)

    meta = topic if topic else NEWS_META
    try:
        cover = generate_cover(
            title=data.get("cover_title") or (topic["title"] if topic else article["title"]),
            subtitle=data.get("cover_subtitle") or "",
            palette=meta["palette"],
            motif=meta["motif"],
            seed=random.randint(0, 10 ** 9),
        )
    except Exception as e:
        if dry_run:
            raise
        _fail(f"ошибка генерации обложки: {str(e)[:200]}")
    log.info("Обложка готова: %d байт", len(cover))

    if dry_run:
        with open("/tmp/news_dry.png", "wb") as f:
            f.write(cover)
        print("── cover_title:", data.get("cover_title"))
        print("── cover_subtitle:", data.get("cover_subtitle"))
        print("── post ──\n" + data["post"])
        return

    if topic:
        meta_line = f"📋 Тема плана: <i>{html.escape(topic['title'])}</i>"
    else:
        meta_line = (f"🔥 Горячая новость: <i>{html.escape(article['title'])}</i>\n"
                     f'📡 {html.escape(article["source"])} · <a href="{article["link"]}">оригинал</a>')

    if send_proposal(data, cover, meta_line):
        if article:
            state.setdefault("sent_news", {})[article["uid"]] = datetime.now(timezone.utc).isoformat()
        save_state(state)
        log.info("Готово")
    else:
        # тему возвращаем в начало цикла, чтобы не потерять
        if topic:
            state["cycle"] = [topic["id"]] + state.get("cycle", [])
            save_state(state)
        _fail("Telegram не принял предложку (sendPhoto) — подробности в journalctl -u tuvpn-news")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        # непредвиденный краш: пытаемся уведомить сами, иначе сработает systemd OnFailure
        log.exception("Необработанная ошибка")
        _fail(f"внутренняя ошибка: {type(e).__name__}: {str(e)[:200]}")
