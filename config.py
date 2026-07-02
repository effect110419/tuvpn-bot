"""
TuVPN config — читает секреты из .env (не коммитим в git!).

Если запускаешь как скрипт первый раз — создай .env по шаблону .env.example.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    # dotenv не установлен — секреты должны быть в окружении напрямую
    pass


def _req(name: str) -> str:
    """Обязательная переменная. Если нет — падаем громко."""
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Переменная окружения {name} не задана. Проверь /root/tuvpn/.env")
    return v


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    try:
        return int(v) if v else default
    except (TypeError, ValueError):
        return default


def _list_int(name: str, default=None) -> list:
    """Парсит '784871620,1027228622' -> [784871620, 1027228622]"""
    raw = os.getenv(name, "")
    if not raw:
        return default or []
    out = []
    for item in raw.split(","):
        item = item.strip()
        if item.isdigit():
            out.append(int(item))
    return out


# ────────────────────────────────────────────────────────────────────
# СЕКРЕТЫ (из .env)
# ────────────────────────────────────────────────────────────────────

# Боты
BOT_TOKEN = _req("BOT_TOKEN")
SUPPORT_BOT_TOKEN = _req("SUPPORT_BOT_TOKEN")
MAIN_BOT_USERNAME = _opt("MAIN_BOT_USERNAME", "MaxArtVPN_bot")

# Supabase
SUPABASE_URL = _req("SUPABASE_URL")
SUPABASE_KEY = _req("SUPABASE_KEY")  # secret key для backend
SUPABASE_PUBLISHABLE_KEY = _opt("SUPABASE_PUBLISHABLE_KEY", "")  # для frontend, опционально

# ЮКасса
YOOKASSA_SHOP_ID = _req("YOOKASSA_SHOP_ID")
YOOKASSA_SECRET_KEY = _req("YOOKASSA_SECRET_KEY")
YOOKASSA_RETURN_URL = _opt("YOOKASSA_RETURN_URL", "https://t.me/MaxArtVPN_bot")
YOOKASSA_WEBHOOK_PATH = _opt("YOOKASSA_WEBHOOK_PATH", "/yookassa/webhook")

# Админка (Telegram-login)
ADMIN_TG_IDS = _list_int("ADMIN_TG_IDS", [784871620, 1027228622])
ADMIN_SESSION_DAYS = _int("ADMIN_SESSION_DAYS", 7)
ADMIN_LOGIN_TOKEN_MINUTES = _int("ADMIN_LOGIN_TOKEN_MINUTES", 10)
FALLBACK_ADMIN_IDS = _list_int("FALLBACK_ADMIN_IDS", ADMIN_TG_IDS)

# Подписки
SUB_BASE_URL = _opt("SUB_BASE_URL", "https://sub.tuvpn.ru")

# Новостной канал (публикация предложек из news_bot)
NEWS_CHANNEL_ID = _opt("NEWS_CHANNEL_ID", "@tuvpn_news")

# ────────────────────────────────────────────────────────────────────
# LEGACY (от первой версии, остаются для совместимости).
# Сейчас серверы берутся из БД (таблица servers), но эти переменные
# используются как fallback в apply_referral_bonus в proxy.py.
# ────────────────────────────────────────────────────────────────────
PANEL_URL = _opt("LEGACY_PANEL_URL", "https://89.125.53.210:17627/I4z8tB7MLF8wPjpKDW")
PANEL_USER = _opt("LEGACY_PANEL_USER", "clmHydSJD6")
PANEL_PASS = _opt("LEGACY_PANEL_PASS", "")
INBOUND_ID = _int("LEGACY_INBOUND_ID", 2)
SERVER_IP = _opt("LEGACY_SERVER_IP", "89.125.53.210")
SUB_URL = _opt("LEGACY_SUB_URL", "https://89.125.53.210:8443/sub.txt")
XUI_API = "/panel/api/inbounds"
