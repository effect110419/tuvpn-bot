import asyncio
import logging
import uuid
import json
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from supabase import create_client
from config import *
import yookassa_client
import re


class BuyStates(StatesGroup):
    waiting_promo = State()
    waiting_email = State()

from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# ══════════════════════════════
# SUPABASE
# ══════════════════════════════
def get_user(user_id):
    try:
        r = sb.table("users").select("*").eq("user_id", user_id).execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logging.error(f"get_user: {e}")
        return None

def register_user(user_id, username, first_name=None, last_name=None, referrer_id=None):
    try:
        if not get_user(user_id):
            data = {"user_id": user_id, "username": username or "", "first_name": first_name or "", "last_name": last_name or ""}
            if referrer_id:
                data["referrer_id"] = referrer_id
            sb.table("users").insert(data).execute()
            return True
        return False
    except Exception as e:
        logging.error(f"register_user: {e}")
        return False

def get_subscription(user_id):
    try:
        r = sb.table("subscriptions").select("*").eq("user_id", user_id).eq("status", "active").execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logging.error(f"get_subscription: {e}")
        return None

def create_db_subscription(user_id, devices, days, client_uuid, sub_url):
    try:
        expires = (datetime.now() + timedelta(days=days)).isoformat()
        sb.table("subscriptions").insert({
            "user_id": user_id, "devices": devices, "status": "active",
            "sub_url": sub_url, "started_at": datetime.now().isoformat(), "expires_at": expires
        }).execute()
        sb.table("users").update({"client_uuid": client_uuid}).eq("user_id", user_id).execute()
        return expires
    except Exception as e:
        logging.error(f"create_db_subscription: {e}")
        return None

def deactivate_subscription(sub_id):
    try:
        sb.table("subscriptions").update({"status": "inactive"}).eq("id", sub_id).execute()
    except Exception as e:
        logging.error(f"deactivate_subscription: {e}")

def extend_db_subscription(sub_id, user_id, days):
    try:
        sub = get_subscription(user_id)
        if sub:
            current = datetime.fromisoformat(sub["expires_at"])
            new_expires = max(current, datetime.now()) + timedelta(days=days)
            sb.table("subscriptions").update({
                "expires_at": new_expires.isoformat(), "status": "active"
            }).eq("id", sub_id).execute()
            return new_expires
        return None
    except Exception as e:
        logging.error(f"extend_db_subscription: {e}")
        return None

# ══════════════════════════════
# ФУНКЦИИ УПРАВЛЕНИЯ УСТРОЙСТВАМИ
# ══════════════════════════════

def get_user_devices(user_id):
    """Получить список активных устройств пользователя (свежие сверху)."""
    try:
        r = (sb.table("user_devices").select("*")
             .eq("user_id", user_id).eq("is_active", True)
             .order("connected_at", desc=False).execute())
        return r.data
    except Exception as e:
        logging.error(f"get_user_devices: {e}")
        return []

def add_user_device(user_id, device_name, device_type, device_info, client_uuid):
    """Добавить новое устройство пользователю"""
    try:
        sb.table("user_devices").insert({
            "user_id": user_id,
            "device_name": device_name,
            "device_type": device_type,
            "device_info": device_info,
            "client_uuid": client_uuid,
        }).execute()
        return True
    except Exception as e:
        logging.error(f"add_user_device: {e}")
        return False

def remove_user_device(user_id, device_id):
    """Удалить устройство пользователя"""
    try:
        sb.table("user_devices").update({"is_active": False}).eq("user_id", user_id).eq("id", device_id).execute()
        return True
    except Exception as e:
        logging.error(f"remove_user_device: {e}")
        return False

def count_active_devices(user_id):
    """Подсчитать количество активных устройств пользователя"""
    try:
        r = sb.table("user_devices").select("id", count="exact").eq("user_id", user_id).eq("is_active", True).execute()
        return r.count
    except Exception as e:
        logging.error(f"count_active_devices: {e}")
        return 0

def get_user_stats(user_id):
    """Получить статистику пользователя для профиля"""
    try:
        user = get_user(user_id)
        if not user:
            return None
        
        sub = get_subscription(user_id)
        devices_count = count_active_devices(user_id)
        
        payments_r = sb.table("payments").select("amount", count="exact").eq("user_id", user_id).eq("status", "succeeded").execute()
        total_paid = sum(float(p.get('amount', 0)) for p in payments_r.data) if payments_r.data else 0
        
        refs_r = sb.table("referrals").select("referred_id", count="exact").eq("referrer_id", user_id).execute()
        referrals_count = refs_r.count
        
        return {
            "user": user,
            "subscription": sub,
            "devices_count": devices_count,
            "payments_count": payments_r.count,
            "total_paid": total_paid,
            "referrals_count": referrals_count
        }
    except Exception as e:
        logging.error(f"get_user_stats: {e}")
        return None

# ══════════════════════════════
# 3X-UI API
# ══════════════════════════════
async def xui_session():
    jar = aiohttp.CookieJar(unsafe=True)
    connector = aiohttp.TCPConnector(ssl=False)
    session = aiohttp.ClientSession(connector=connector, cookie_jar=jar)
    await session.post(f"{PANEL_URL}/login", json={"username": PANEL_USER, "password": PANEL_PASS})
    return session

async def xui_add_client(user_id, devices, days):
    client_uuid = str(uuid.uuid4())
    email = f"user_{user_id}"
    expire_ms = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
    session = await xui_session()
    try:
        payload = {
            "id": INBOUND_ID,
            "settings": json.dumps({"clients": [{
                "id": client_uuid, "email": email, "limitIp": devices,
                "totalGB": 0, "expiryTime": expire_ms, "enable": True, "flow": "xtls-rprx-vision"
            }]})
        }
        resp = await session.post(f"{PANEL_URL}/panel/api/inbounds/addClient", json=payload)
        data = await resp.json()
        await session.close()
        if data.get("success"):
            sub_url = f"{SUB_BASE_URL}/sub/{client_uuid}"
            return client_uuid, sub_url
        logging.error(f"xui_add_client error: {data}")
    except Exception as e:
        logging.error(f"xui_add_client exception: {e}")
        await session.close()
    return None, None

async def xui_toggle_client(client_uuid, user_id, enable, devices=1):
    email = f"user_{user_id}"
    session = await xui_session()
    try:
        payload = {
            "id": INBOUND_ID,
            "settings": json.dumps({"clients": [{
                "id": client_uuid, "email": email, "limitIp": devices,
                "enable": enable, "flow": "xtls-rprx-vision"
            }]})
        }
        await session.post(f"{PANEL_URL}/panel/api/inbounds/updateClient/{client_uuid}", json=payload)
    except Exception as e:
        logging.error(f"xui_toggle_client: {e}")
    await session.close()

async def xui_extend_client(client_uuid, user_id, devices, days):
    email = f"user_{user_id}"
    expire_ms = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
    session = await xui_session()
    try:
        payload = {
            "id": INBOUND_ID,
            "settings": json.dumps({"clients": [{
                "id": client_uuid, "email": email, "limitIp": devices,
                "expiryTime": expire_ms, "enable": True, "flow": "xtls-rprx-vision"
            }]})
        }
        await session.post(f"{PANEL_URL}/panel/api/inbounds/updateClient/{client_uuid}", json=payload)
    except Exception as e:
        logging.error(f"xui_extend_client: {e}")
    await session.close()

# ══════════════════════════════
# РЕФЕРАЛЬНАЯ СИСТЕМА
# ══════════════════════════════
async def give_referral_bonus(user_id, days, reason):
    """Начислить дни существующей подписке через issue_subscription (все серверы).
    Если активной подписки нет — копим в users.bonus_days."""
    try:
        sub = get_subscription(user_id)
        if sub:
            from proxy import issue_subscription as _issue
            _res = _issue(user_id, sub.get("devices", 1), days)
            logging.info(f"referral bonus issued for {user_id}: {_res}")
        else:
            try:
                u = sb.table("users").select("bonus_days").eq("user_id", user_id).limit(1).execute()
                cur = (u.data[0].get("bonus_days") if u.data else 0) or 0
                sb.table("users").update({"bonus_days": cur + days}).eq("user_id", user_id).execute()
                logging.info(f"referral bonus accumulated for {user_id}: +{days} (total {cur + days})")
            except Exception as e:
                logging.error(f"accumulate bonus_days failed: {e}")
        try:
            text_lines = [
                f"🎁 Вам начислено <b>{days} дней бонуса</b>!",
                "",
                f"Причина: {reason}",
            ]
            await bot.send_message(user_id, "\n".join(text_lines), parse_mode="HTML")
        except Exception:
            pass
    except Exception as e:
        logging.error(f"give_referral_bonus: {e}")


async def give_new_user_bonus(user_id, days=7):
    """Выдать новому юзеру подписку через issue_subscription — на все активные серверы."""
    try:
        from proxy import issue_subscription as _issue
        res = _issue(user_id, 1, days)
        logging.info(f"new user bonus for {user_id}: {res}")
        if res.get("success"):
            try:
                text_lines = [
                    f"🎁 Вам начислено <b>{days} дней</b> бесплатного доступа!",
                    "",
                    "Откройте <b>«🔌 Подключиться»</b> в меню — там ссылка и инструкция.",
                ]
                await bot.send_message(user_id, "\n".join(text_lines), parse_mode="HTML")
            except Exception:
                pass
        else:
            logging.error(f"give_new_user_bonus issue failed: {res}")
    except Exception as e:
        logging.error(f"give_new_user_bonus: {e}")

# ══════════════════════════════
# ПРОВЕРКА ИСТЁКШИХ ПОДПИСОК
# ══════════════════════════════
async def check_expired():
    """
    Каждый час проверяет подписки и шлёт уведомления:
    - За 3 дня до истечения (один раз, флаг notified_3d)
    - За 1 день до истечения (один раз, флаг notified_1d)
    - При истечении — деактивирует + шлёт сообщение (флаг notified_expired)
    """
    while True:
        try:
            r = sb.table("subscriptions").select("*").eq("status", "active").execute()
            now = datetime.now()
            for sub in (r.data or []):
                try:
                    expires = datetime.fromisoformat(sub["expires_at"])
                    if expires.tzinfo is not None:
                        expires = expires.replace(tzinfo=None)
                except Exception:
                    continue

                days_left = (expires - now).total_seconds() / 86400
                user_id = sub["user_id"]
                sub_id = sub["id"]

                # ИСТЕКЛА
                if days_left <= 0:
                    deactivate_subscription(sub_id)
                    user = get_user(user_id)
                    client_uuid = user.get("client_uuid") if user else None
                    if client_uuid:
                        try:
                            await xui_toggle_client(client_uuid, user_id, False, sub.get("devices", 1))
                        except Exception as e:
                            logging.error(f"xui_toggle_client error: {e}")
                    if not sub.get("notified_expired"):
                        try:
                            await bot.send_message(
                                user_id,
                                "⚠️ <b>Ваша подписка TuVPN истекла</b>\n\n"
                                "Продлите подписку чтобы восстановить доступ к VPN. "
                                "Все ваши настройки сохранены — после оплаты ничего не нужно перенастраивать.",
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="🛒 Продлить подписку", callback_data="buy")],
                                    [InlineKeyboardButton(text="💬 Поддержка", url="https://t.me/TuVPNSupport_bot")],
                                ])
                            )
                        except Exception as e:
                            logging.warning(f"notify_expired failed user={user_id}: {e}")
                        try:
                            sb.table("subscriptions").update({"notified_expired": True}).eq("id", sub_id).execute()
                        except Exception:
                            pass
                    continue

                # ЗА 1 ДЕНЬ ДО ИСТЕЧЕНИЯ
                if days_left <= 1 and not sub.get("notified_1d"):
                    try:
                        await bot.send_message(
                            user_id,
                            f"⏰ <b>Завтра истекает ваша подписка TuVPN</b>\n\n"
                            f"📅 Активна до: <b>{expires.strftime('%d.%m.%Y %H:%M')}</b>\n"
                            f"📱 Тариф: {sub.get('devices', 1)} устр.\n\n"
                            f"Продлите сейчас — и не останетесь без VPN. "
                            f"Все ваши настройки сохранятся, ничего не нужно перенастраивать.",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🛒 Продлить", callback_data="buy")],
                                [InlineKeyboardButton(text="◀️ В меню", callback_data="back")],
                            ])
                        )
                    except Exception as e:
                        logging.warning(f"notify_1d failed user={user_id}: {e}")
                    try:
                        sb.table("subscriptions").update({"notified_1d": True}).eq("id", sub_id).execute()
                    except Exception:
                        pass
                    continue

                # ЗА 3 ДНЯ ДО ИСТЕЧЕНИЯ
                if days_left <= 3 and not sub.get("notified_3d"):
                    try:
                        await bot.send_message(
                            user_id,
                            f"⏳ <b>Через 3 дня истекает ваша подписка TuVPN</b>\n\n"
                            f"📅 Активна до: <b>{expires.strftime('%d.%m.%Y')}</b>\n"
                            f"📱 Тариф: {sub.get('devices', 1)} устр.\n\n"
                            f"Продлите заранее чтобы не остаться без VPN. "
                            f"Не забудьте — за продление друзей вы получаете +7 дней 🎁",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🛒 Продлить", callback_data="buy")],
                                [InlineKeyboardButton(text="🤝 Позвать друга", callback_data="referral")],
                            ])
                        )
                    except Exception as e:
                        logging.warning(f"notify_3d failed user={user_id}: {e}")
                    try:
                        sb.table("subscriptions").update({"notified_3d": True}).eq("id", sub_id).execute()
                    except Exception:
                        pass
        except Exception as e:
            logging.error(f"check_expired loop error: {e}")
        await asyncio.sleep(3600)

# ══════════════════════════════
# ЦЕНЫ
# ══════════════════════════════
PRICES = {
    1: {"1": 149, "3": 399, "12": 1399},
    2: {"1": 249, "3": 649, "12": 2299},
    5: {"1": 599, "3": 1599, "12": 5499},
}

# === TG STARS PAYMENT ===
# Цены в Stars: коэффициент ~0.54 от рубля (т.к. юзер платит ~2₽ за 1⭐)
PRICES_STARS = {
    1: {"1": 80,  "3": 215,  "12": 755},
    2: {"1": 135, "3": 350,  "12": 1240},
    5: {"1": 325, "3": 865,  "12": 2970},
}
DAYS = {"1": 30, "3": 90, "12": 365}

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Подключиться", callback_data="connect")],
        [InlineKeyboardButton(text="🛒 Оформить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton(text="📋 Как подключиться", callback_data="howto"),
         InlineKeyboardButton(text="🤝 Позвать друга", callback_data="referral")],
        [InlineKeyboardButton(text="📣 Наш канал", callback_data="channel")],
        [InlineKeyboardButton(text="🔎 О сервисе", callback_data="about"),
         InlineKeyboardButton(text="🛠 Помощь", callback_data="support")],
    ])

@dp.message(Command("start"))
async def start(message: types.Message):
    args = message.text.split()

    # === ADMIN LOGIN DEEPLINK ===
    if len(args) > 1 and args[1].startswith("login_admin_"):
        login_token = args[1][len("login_admin_"):]
        tg_id = message.from_user.id
        if tg_id not in ADMIN_TG_IDS:
            await message.answer(
                "❌ <b>Доступ к админке запрещён</b>\n\n"
                "Ваш Telegram ID не находится в списке администраторов TuVPN.",
                parse_mode="HTML",
            )
            return
        # Проверим что попытка существует и pending
        try:
            r = sb.table("admin_login_attempts").select("status,expires_at").eq("login_token", login_token).limit(1).execute()
            if not r.data:
                await message.answer("❌ Сессия логина не найдена. Откройте админку и попробуйте снова.")
                return
            if r.data[0]["status"] != "pending":
                await message.answer(f"⚠ Эта ссылка уже использована или истекла (status: {r.data[0]['status']}).")
                return
        except Exception as e:
            logging.error(f"admin login lookup: {e}")
            await message.answer(f"Ошибка БД: {e}")
            return

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Подтвердить вход", callback_data=f"adm_login_confirm:{login_token}")],
            [InlineKeyboardButton(text="❌ Это не я", callback_data=f"adm_login_cancel:{login_token}")],
        ])
        await message.answer(
            "🔐 <b>Вход в админку TuVPN</b>\n\n"
            "Кто-то запросил вход в админ-панель с вашим Telegram ID.\n"
            "Если это вы — нажмите «Подтвердить вход».\n"
            "Если нет — нажмите «Это не я».",
            reply_markup=kb,
            parse_mode="HTML",
        )
        return
    # === END ADMIN LOGIN DEEPLINK ===

# UTM campaigns: check string parameters
    campaign = None
    if len(args) > 1 and not args[1].isdigit():
        try:
            r = sb.table("campaigns").select("*").eq("code", args[1]).eq("is_active", True).limit(1).execute()
            if r.data:
                campaign = r.data[0]
        except Exception as e:
            logging.error(f"UTM lookup: {e}")
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    user_id = message.from_user.id
    first_name = message.from_user.first_name or ""

    is_new = register_user(user_id, message.from_user.username,
                           first_name, message.from_user.last_name, referrer_id)
# === UTM FIX 2026-05 === — process new user from campaign
    if is_new and campaign:
        try:
            sb.table("users").update({"campaign_code": campaign["code"]}).eq("user_id", user_id).execute()
            sb.table("campaign_clicks").insert({
                "campaign_code": campaign["code"],
                "user_id": user_id,
                "is_new_user": True,
            }).execute()
            bonus_days = int(campaign.get("bonus_days") or 7)

            # UTM v2 — direct issue_subscription call (без HTTP, без admin auth)
            try:
                from proxy import issue_subscription as _issue
                _res = _issue(user_id, 1, bonus_days)
                logging.info(f"UTM issue_subscription for {user_id}: {_res}")
            except Exception as ge:
                logging.error(f"UTM issue_subscription failed: {ge}")

            # welcome — с дефолтом если null/пусто
            welcome = (campaign.get("welcome_text") or "").strip()
            if not welcome:
                welcome = (
                    f"🎁 <b>Добро пожаловать{', ' + first_name if first_name else ''}!</b>\n\n"
                    f"Спасибо что перешёл по ссылке — мы дарим тебе "
                    f"<b>{bonus_days} дней бесплатного доступа</b> к TuVPN 🚀\n\n"
                    f"✅ Подписка уже активна\n"
                    f"📱 Доступно: 1 устройство\n\n"
                    f"Открой «🔌 Подключиться» в меню ниже."
                )
            await message.answer(welcome, reply_markup=main_menu(), parse_mode="HTML")
            return
        except Exception as e:
            logging.error(f"UTM processing: {e}")
            # Не падаем молча — отвечаем юзеру дефолтным сообщением
            try:
                await message.answer(
                    f"🎁 Добро пожаловать{', ' + first_name if first_name else ''}!\n\n"
                    f"Спасибо что перешёл к нам. Открой меню и оформи подписку.",
                    reply_markup=main_menu()
                )
            except Exception:
                pass
            return

    if is_new and referrer_id and referrer_id != user_id:
        try:
            sb.table("referrals").insert({"referrer_id": referrer_id, "referred_id": user_id}).execute()
            await give_new_user_bonus(user_id, 7)
            await give_referral_bonus(referrer_id, 3, "Друг перешёл по вашей ссылке")
        except Exception as e:
            logging.error(f"referral processing: {e}")

        await message.answer(
            f"🎁 <b>Добро пожаловать{', ' + first_name if first_name else ''}!</b>\n\n"
            f"Ваш друг пригласил вас в <b>TuVPN</b> — мы дарим вам "
            f"<b>7 дней бесплатного доступа</b> 🚀\n\n"
            f"✅ Подписка уже активна\n"
            f"📱 Доступно: 1 устройство\n\n"
            f"Чтобы начать — нажмите <b>«🔌 Подключиться»</b> в меню ниже.",
            reply_markup=main_menu()
        )
        return

    sub = get_subscription(user_id)
    if sub:
        try:
            from datetime import datetime as _dt
            exp = _dt.fromisoformat(sub["expires_at"].replace("Z", "+00:00"))
            if exp.tzinfo is not None:
                exp = exp.replace(tzinfo=None)
            days_left = max(0, (exp - _dt.now()).days)
        except Exception:
            days_left = 0

        greeting = f"С возвращением{', ' + first_name if first_name else ''}! 👋"
        if days_left > 0:
            text = (
                f"{greeting}\n\n"
                f"✅ Ваша подписка активна\n"
                f"📅 До: <b>{exp.strftime('%d.%m.%Y')}</b> (осталось {days_left} дн.)\n"
                f"📱 Устройств: <b>{sub['devices']}</b>\n\n"
                f"Откройте «🔌 Подключиться» — там ссылка и инструкция."
            )
        else:
            text = (
                f"{greeting}\n\n"
                f"⚠️ Ваша подписка <b>истекла</b>\n\n"
                f"Продлите её — нажмите «🛒 Оформить подписку»."
            )
        await message.answer(text, reply_markup=main_menu())
        return

    await message.answer(
        f"Привет{', ' + first_name if first_name else ''}! 👋\n\n"
        f"🌊 <b>TuVPN</b> — просто включи и пользуйся.\n\n"
        f"⚡️ Подписка активна сразу после оплаты\n"
        f"💰 Честные цены без переплат\n"
        f"🎬 Instagram, YouTube, Telegram — всё открыто\n"
        f"🔒 VLESS+Reality — современный незаметный протокол\n\n"
        f"Нажмите «🛒 Оформить подписку» чтобы начать.",
        reply_markup=main_menu()
    )

@dp.message(Command("menu"))
async def menu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu())

@dp.callback_query(lambda c: c.data == "connect")
async def connect(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    sub = get_subscription(user_id)

    if sub:
        try:
            from datetime import datetime as _dt
            exp = _dt.fromisoformat(sub["expires_at"].replace("Z", "+00:00"))
            if exp.tzinfo is not None:
                exp = exp.replace(tzinfo=None)
            days_left = max(0, (exp - _dt.now()).days)
        except Exception:
            days_left = 0

        if days_left > 0:
            devices_count = count_active_devices(user_id)
            device_limit = sub.get('devices', 1)
            
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Ссылка подключения", callback_data="connection_link")],
                [InlineKeyboardButton(text="📱 Мои устройства", callback_data="my_devices")],
                [InlineKeyboardButton(text="➕ Добавить устройства", callback_data="add_devices")],
                [InlineKeyboardButton(text="📲 Как настроить", callback_data="howto")],
                [InlineKeyboardButton(text="🔄 Продлить / изменить тариф", callback_data="buy")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
            ])
            text = (
                f"🔌 <b>Подключение к TuVPN</b>\n\n"
                f"✅ Подписка активна\n"
                f"📅 До: <b>{exp.strftime('%d.%m.%Y')}</b> (осталось {days_left} дн.)\n"
                f"📱 Устройств: <b>{devices_count}/{device_limit}</b>\n\n"
                f"Выберите действие:"
            )
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Продлить подписку", callback_data="buy")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
            ])
            text = (
                f"🔌 <b>Подключение к TuVPN</b>\n\n"
                f"⚠️ Ваша подписка <b>истекла</b>\n\n"
                f"Продлите её — и сразу сможете пользоваться."
            )
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Оформить подписку", callback_data="buy")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
        ])
        text = (
            f"🔌 <b>Подключение к TuVPN</b>\n\n"
            f"❌ У вас пока нет активной подписки\n\n"
            f"Чтобы пользоваться TuVPN — оформите подписку. Это займёт 1 минуту, а после оплаты ссылка появится прямо здесь."
        )
    await callback.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "buy")
async def buy(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔹 1 устройство", callback_data="devices_1")],
        [InlineKeyboardButton(text="🔹 2 устройства", callback_data="devices_2")],
        [InlineKeyboardButton(text="🔹 5 устройств", callback_data="devices_5")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])
    await callback.message.answer("🛒 На сколько устройств нужен VPN?", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("devices_"))
async def choose_period(callback: types.CallbackQuery):
    devices = int(callback.data.split("_")[1])
    p = PRICES[devices]
    # Считаем скидки относительно цены за месяц при покупке на 1 мес
    price_per_month_1 = p["1"]
    price_per_month_3 = p["3"] / 3
    price_per_month_12 = p["12"] / 12
    discount_3 = round((1 - price_per_month_3 / price_per_month_1) * 100)
    discount_12 = round((1 - price_per_month_12 / price_per_month_1) * 100)

    label_3 = f"📆 3 месяца — {p['3']} ₽"
    if discount_3 > 0:
        label_3 += f" (−{discount_3}%)"

    label_12 = f"🏆 1 год — {p['12']} ₽"
    if discount_12 > 0:
        label_12 += f" 🔥 −{discount_12}%"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🗓 1 месяц — {p['1']} ₽", callback_data=f"period_{devices}_1")],
        [InlineKeyboardButton(text=label_3, callback_data=f"period_{devices}_3")],
        [InlineKeyboardButton(text=label_12, callback_data=f"period_{devices}_12")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")],
    ])
    await callback.message.answer(
        f"🌊 <b>Оформление подписки TuVPN</b>\n\n"
        f"🔹 Устройств: <b>{devices}</b>\n"
        f"Выберите период — чем дольше, тем выгоднее:",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("period_"))
async def choose_payment(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    devices = int(parts[1])
    months = parts[2]
    price = PRICES[devices][months]
    days = DAYS[months]
    months_label = {"1": "1 месяц", "3": "3 месяца", "12": "1 год"}[months]
    # === TG STARS PAYMENT ===
    stars_price = PRICES_STARS[devices][months]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Банковская карта РФ", callback_data=f"pay_card_{devices}_{months}")],
        [InlineKeyboardButton(text=f"⭐ Telegram Stars — {stars_price}⭐", callback_data=f"pay_stars_{devices}_{months}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"devices_{devices}")],
    ])
    await callback.message.answer(
        f"📋 Оплата подписки\n\n"
        f"📦 {months_label} / {devices} уст. / {price} ₽ / {days} дней\n\n"
        f"Выберите способ оплаты:\n\n"
        f"<i>💡 Оплата Stars работает только в мобильном Telegram (iOS, Android) и Desktop. В Telegram Web — недоступна.</i>",
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("pay_card_"))
async def pay_card(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    devices = int(parts[2])
    months = parts[3]
    price = PRICES[devices][months]
    months_label = {"1": "1 месяц", "3": "3 месяца", "12": "1 год"}[months]

    # Сохраняем выбор пользователя
    await state.update_data(devices=devices, months=months, price=price, months_label=months_label)

    # Проверяем активную подписку
    user_id = callback.from_user.id
    sub = get_subscription(user_id)
    days_left = 0
    if sub:
        try:
            from datetime import datetime as _dt
            exp = _dt.fromisoformat(sub["expires_at"].replace("Z", "+00:00"))
            if exp.tzinfo is not None:
                exp = exp.replace(tzinfo=None)
            days_left = max(0, (exp - _dt.now()).days)
        except Exception:
            days_left = 0

    # Если активной подписки нет или она истекла — обычный flow
    if not sub or days_left <= 0:
        await _ask_promo(callback.message, state, devices, months, price, months_label)
        await callback.answer()
        return

    current_devices = sub.get("devices", 1)
    days_in_period = {"1": 30, "3": 90, "12": 365}[months]

    # Сценарий: тот же тариф по устройствам
    if current_devices == devices:
        text = (
            f"♻️ <b>У вас активная подписка</b>\n\n"
            f"📱 Устройств: {current_devices}\n"
            f"⏳ Осталось: {days_left} дн.\n\n"
            f"После оплаты:\n"
            f"📦 {months_label} / {devices} уст. / {price} ₽\n"
            f"➕ К сроку добавится: {days_in_period} дн.\n"
            f"⏳ Итого станет: {days_left + days_in_period} дн.\n\n"
            f"Продолжить?"
        )
    elif devices > current_devices:
        # Повышение тарифа
        text = (
            f"⬆️ <b>Повышение тарифа</b>\n\n"
            f"📱 Сейчас: {current_devices} уст.\n"
            f"⏳ Осталось: {days_left} дн.\n\n"
            f"После оплаты:\n"
            f"📱 Устройств станет: <b>{devices}</b>\n"
            f"➕ К сроку добавится: {days_in_period} дн.\n"
            f"⏳ Итого станет: {days_left + days_in_period} дн.\n"
            f"💰 К оплате: {price} ₽\n\n"
            f"Продолжить?"
        )
    else:
        # Понижение тарифа — строгое предупреждение
        text = (
            f"⚠️ <b>ВНИМАНИЕ: понижение тарифа</b>\n\n"
            f"📱 Сейчас у вас: <b>{current_devices} уст.</b>\n"
            f"⏳ Осталось: {days_left} дн.\n\n"
            f"Вы выбираете тариф на <b>{devices} уст.</b> — это <b>меньше</b> чем сейчас.\n\n"
            f"После оплаты:\n"
            f"• Лимит устройств станет: <b>{devices}</b>\n"
            f"• Лишние подключения будут отключены\n"
            f"• К сроку добавится: {days_in_period} дн. (станет {days_left + days_in_period})\n"
            f"• К оплате: {price} ₽\n\n"
            f"Уверены что хотите понизить тариф?"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, продолжить", callback_data="confirm_buy")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_buy")],
    ])
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data == "confirm_buy")
async def confirm_buy(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    devices = data.get("devices")
    months = data.get("months")
    price = data.get("price")
    months_label = data.get("months_label")
    if not all([devices, months, price, months_label]):
        await callback.answer("Сессия истекла, начните заново через /start", show_alert=True)
        await state.clear()
        return
    await _ask_promo(callback.message, state, devices, months, price, months_label)
    await callback.answer()


async def _ask_promo(message, state: FSMContext, devices, months, price, months_label):
    """Спрашивает у пользователя есть ли промокод."""
    await state.update_data(
        devices=devices, months=months, price=price, months_label=months_label,
        promo_id=None, promo_code=None, promo_type=None, promo_value=None,
        final_price=price, bonus_days_from_promo=0,
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 У меня есть промокод", callback_data="have_promo")],
        [InlineKeyboardButton(text="➡️ Без промокода", callback_data="no_promo")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_buy")],
    ])
    await message.answer(
        f"🎁 <b>Есть ли у вас промокод?</b>\n\n"
        f"📦 {months_label} / {devices} уст.\n"
        f"💰 Сумма: {price} ₽\n\n"
        f"Если есть промокод — введите его и получите скидку или бонусные дни.",
        reply_markup=kb,
    )


async def _ask_email(message, state: FSMContext):
    """БЕЗ запроса email. Сразу создаёт платёж ЮКассы с техническим email
    и показывает кнопку «Оплатить». Email больше не спрашиваем у юзера."""
    data = await state.get_data()
    devices = data.get("devices")
    months = data.get("months")
    base_price = data.get("price")
    final_price = data.get("final_price", base_price)
    months_label = data.get("months_label")
    promo_id = data.get("promo_id")
    promo_code = data.get("promo_code")
    promo_type = data.get("promo_type")
    promo_value = data.get("promo_value")
    bonus_days_from_promo = data.get("bonus_days_from_promo", 0)

    user_id = message.chat.id
    # Технический email — юзер его не вводит, чек формируется в «Мой налог»
    email = f"user_{user_id}@tuvpn.ru"
    description = f"Подписка TuVPN: {months_label}, {devices} уст."
    if promo_code:
        description += f" (промо {promo_code})"

    try:
        payment = yookassa_client.create_payment(
            amount=final_price,
            description=description,
            user_id=user_id,
            devices=devices,
            months=int(months),
            email=email,
            promo_id=promo_id,
            promo_code=promo_code,
            promo_type=promo_type,
            promo_value=promo_value,
            bonus_days_from_promo=bonus_days_from_promo,
        )
    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await message.answer("⚠️ Не удалось создать платёж. Попробуйте позже или напишите в @TuVPNSupport_bot")
        await state.clear()
        return

    # Записываем платёж в БД (pending)
    try:
        payment_meta = {
            "base_price": base_price, "final_price": final_price,
            "promo_id": promo_id, "promo_code": promo_code,
            "promo_type": promo_type, "promo_value": promo_value,
            "bonus_days_from_promo": bonus_days_from_promo,
        }
        sb.table("payments").insert({
            "provider": "yookassa",
            "provider_payment_id": payment["payment_id"],
            "user_id": user_id,
            "amount": final_price,
            "currency": "RUB",
            "status": payment["status"],
            "email": email,
            "devices": devices,
            "months": int(months),
            "description": description,
            "confirmation_url": payment["confirmation_url"],
            "metadata": payment_meta,
        }).execute()
    except Exception as e:
        logging.error(f"Не удалось записать платёж в БД: {e}")

    await state.clear()

    promo_line = ""
    if promo_code:
        if promo_type == "percent":
            promo_line = f"\n🎁 Промокод {promo_code}: −{promo_value}%"
        else:
            promo_line = f"\n🎁 Промокод {promo_code}: +{promo_value} дн."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back")],
    ])
    await message.answer(
        f"✅ <b>Платёж создан!</b>\n\n"
        f"📦 {months_label} / {devices} уст.{promo_line}\n"
        f"💰 К оплате: <b>{final_price} ₽</b>\n\n"
        f"Нажмите «💳 Оплатить» чтобы перейти к оплате.\n"
        f"После успешной оплаты ссылка для подключения появится в разделе «🔌 Подключиться».\n\n"
        f"💡 Если передумали — просто закройте этот экран, платёж не пройдёт без оплаты в течение 30 минут.",
        reply_markup=kb,
    )


# === TG STARS PAYMENT ===
@dp.callback_query(lambda c: c.data.startswith("pay_stars_"))
async def pay_stars(callback: types.CallbackQuery, state: FSMContext):
    """Создаёт Telegram-инвойс на оплату звёздами."""
    parts = callback.data.split("_")
    devices = int(parts[2])
    months = parts[3]
    stars_amount = PRICES_STARS[devices][months]
    rub_price = PRICES[devices][months]
    days = DAYS[months]
    months_label = {"1": "1 месяц", "3": "3 месяца", "12": "1 год"}[months]

    # payload — в нём передадим user_id + параметры подписки
    user_id = callback.from_user.id
    payload = f"tuvpn_stars:{user_id}:{devices}:{months}:{days}"

    try:
        await bot.send_invoice(
            chat_id=user_id,
            title=f"TuVPN — {months_label}, {devices} устр.",
            description=(
                f"Подписка TuVPN на {months_label} ({days} дней)\n"
                f"До {devices} устройств. Оплата звёздами Telegram."
            ),
            payload=payload,
            currency="XTR",
            prices=[types.LabeledPrice(label="TuVPN Subscription", amount=stars_amount)],
            start_parameter=f"tuvpn-{devices}-{months}",
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"send_invoice failed: {e}")
        await callback.message.answer(f"❌ Не удалось создать инвойс: {e}")
        await callback.answer()


@dp.pre_checkout_query()
async def process_pre_checkout(pre_q: types.PreCheckoutQuery):
    """Telegram обязательно запрашивает подтверждение готовности до списания звёзд."""
    try:
        await bot.answer_pre_checkout_query(pre_q.id, ok=True)
    except Exception as e:
        logging.error(f"pre_checkout failed: {e}")
        try:
            await bot.answer_pre_checkout_query(pre_q.id, ok=False, error_message="Внутренняя ошибка, попробуйте позже")
        except Exception:
            pass


@dp.message(lambda m: m.successful_payment is not None)
async def process_successful_payment(message: types.Message):
    """Ловит успешную оплату звёздами. Выдаёт подписку, уведомляет админов."""
    sp = message.successful_payment
    user_id = message.from_user.id
    first_name = message.from_user.first_name or ""

    if sp.currency != "XTR":
        # Неожиданно, но ладно — не Stars-оплата, не наш случай
        return

    # payload: tuvpn_stars:<uid>:<devices>:<months>:<days>
    try:
        parts = sp.invoice_payload.split(":")
        devices = int(parts[2])
        months = parts[3]
        days = int(parts[4])
    except Exception as e:
        logging.error(f"bad payload: {sp.invoice_payload}, error: {e}")
        await message.answer("⚠ Платёж получен, но не удалось распознать параметры. Свяжитесь с поддержкой.")
        return

    stars_amount = sp.total_amount  # уже в Stars (XTR)
    months_label = {"1": "1 месяц", "3": "3 месяца", "12": "1 год"}[months]

    # Записываем платёж в БД
    try:
        sb.table("payments").insert({
            "user_id": user_id,
            "provider_payment_id": sp.telegram_payment_charge_id or sp.provider_payment_charge_id or f"stars_{user_id}_{int(datetime.now().timestamp())}",
            "amount": stars_amount,
            "status": "succeeded",
            "paid_at": datetime.now().isoformat(),
            "metadata": {
                "currency": "XTR",
                "provider": "telegram_stars",
                "devices": devices,
                "months": months,
                "stars": stars_amount,
                "telegram_payment_charge_id": sp.telegram_payment_charge_id,
            },
        }).execute()
    except Exception as e:
        logging.error(f"payment insert failed: {e}")

    # Выдаём подписку через issue_subscription
    try:
        from proxy import issue_subscription as _issue
        result = _issue(user_id, devices, days)
        logging.info(f"Stars issue_subscription for {user_id}: {result}")
    except Exception as e:
        logging.error(f"Stars issue_subscription failed: {e}")
        await message.answer("⚠ Оплата прошла, но не удалось активировать подписку. Свяжитесь с @TuVPNSupport_bot")
        return

    # Уведомляем юзера
    try:
        await message.answer(
            f"✅ <b>Оплата получена!</b>\n\n"
            f"📦 {months_label}, {devices} устр.\n"
            f"💫 Списано: <b>{stars_amount}⭐</b>\n\n"
            f"Подписка активирована. Открой раздел <b>«🔌 Подключиться»</b> в меню — там ссылка и инструкция.",
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Уведомляем админов
    admin_text = (
        f"💰 <b>Новая оплата (Stars)!</b>\n\n"
        f"👤 user_id: <code>{user_id}</code>\n"
        f"👤 Имя: {first_name}\n"
        f"📦 {months_label}, {devices} уст.\n"
        f"💫 Сумма: <b>{stars_amount}⭐</b>\n"
        f"🆔 Платёж: <code>{sp.telegram_payment_charge_id or 'stars'}</code>"
    )
    try:
        admins_res = sb.table("support_admins").select("user_id").eq("is_active", True).execute()
        for a in (admins_res.data or []):
            try:
                await bot.send_message(a["user_id"], admin_text, parse_mode="HTML")
            except Exception as e:
                logging.error(f"notify admin {a.get('user_id')} failed: {e}")
    except Exception as e:
        logging.error(f"Не удалось уведомить админов о Stars-оплате: {e}")




@dp.callback_query(lambda c: c.data == "cancel_buy")
async def cancel_buy(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "Покупка отменена. Что дальше?",
        reply_markup=main_menu()
    )
    await callback.answer()


@dp.message(BuyStates.waiting_email)
async def process_email(message: types.Message, state: FSMContext):
    email = (message.text or "").strip()

    # Простая валидация email
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        await message.answer("❌ Это не похоже на email. Попробуйте ещё раз или нажмите «Отменить».")
        return

    data = await state.get_data()
    devices = data["devices"]
    months = data["months"]
    base_price = data["price"]
    final_price = data.get("final_price", base_price)
    months_label = data["months_label"]
    promo_id = data.get("promo_id")
    promo_code = data.get("promo_code")
    promo_type = data.get("promo_type")
    promo_value = data.get("promo_value")
    bonus_days_from_promo = data.get("bonus_days_from_promo", 0)

    user_id = message.from_user.id
    description = f"TuVPN: {months_label}, {devices} уст."
    if promo_code:
        description += f" (промо {promo_code})"

    try:
        payment = yookassa_client.create_payment(
            amount=final_price,
            description=description,
            user_id=user_id,
            devices=devices,
            months=int(months),
            email=email,
            promo_id=promo_id,
            promo_code=promo_code,
            promo_type=promo_type,
            promo_value=promo_value,
            bonus_days_from_promo=bonus_days_from_promo,
        )
    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await message.answer(
            f"⚠️ Не удалось создать платёж. Попробуйте позже или напишите в поддержку @TuVPNSupport_bot"
        )
        await state.clear()
        return

    # Записываем платёж в Supabase в статусе pending
    try:
        payment_meta = {
            "base_price": base_price,
            "final_price": final_price,
            "promo_id": promo_id,
            "promo_code": promo_code,
            "promo_type": promo_type,
            "promo_value": promo_value,
            "bonus_days_from_promo": bonus_days_from_promo,
        }
        sb.table("payments").insert({
            "provider": "yookassa",
            "provider_payment_id": payment["payment_id"],
            "user_id": user_id,
            "amount": final_price,
            "currency": "RUB",
            "status": payment["status"],
            "email": email,
            "devices": devices,
            "months": int(months),
            "description": description,
            "confirmation_url": payment["confirmation_url"],
            "metadata": payment_meta,
        }).execute()
    except Exception as e:
        logging.error(f"Не удалось записать платёж в БД: {e}")

    await state.clear()

    promo_line = ""
    if promo_code:
        if promo_type == "percent":
            promo_line = f"\n🎁 Промокод {promo_code}: −{promo_value}%"
        else:
            promo_line = f"\n🎁 Промокод {promo_code}: +{promo_value} дн."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back")],
    ])
    await message.answer(
        f"✅ <b>Платёж создан!</b>\n\n"
        f"📦 {months_label} / {devices} уст.{promo_line}\n"
        f"💰 К оплате: <b>{final_price} ₽</b>\n"
        f"📧 Email для чека: {email}\n\n"
        f"Нажмите «💳 Оплатить» чтобы перейти к оплате.\n"
        f"После успешной оплаты ссылка для подключения появится в боте в разделе «🔌 Подключиться».\n\n"
        f"💡 Если передумали — просто закройте этот экран, платёж не пройдёт без оплаты в течение 30 минут.",
        reply_markup=kb,
    )

@dp.callback_query(lambda c: c.data == "channel")
async def channel(callback: types.CallbackQuery):
    # === CHANNEL UPDATED ===
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Открыть канал", url="https://t.me/tuvpn_news")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])
    await callback.message.answer(
        "📣 <b>Канал TuVPN — Новости</b>\n\n"
        "Здесь мы публикуем:\n"
        "• Обновления сервиса (новые страны, фичи)\n"
        "• Полезное про VPN, обход блокировок\n"
        "• Промокоды для подписчиков\n"
        "• Технические анонсы\n\n"
        "Подпишись — будешь в курсе всех новинок 🚀",
        reply_markup=kb,
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "about")
async def about(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back")]])
    await callback.message.answer(
        "🌊 TuVPN — твой надёжный щит в сети\n\n"
        "Стабильный • Быстрый • Безопасный\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "💎 ПОЧЕМУ TUVPN:\n"
        "🏎 Скорость → Без тормозов и просадок\n"
        "🌍 Серверы: Финляндия 🇫🇮 · Нидерланды 🇳🇱 · Германия 🇩🇪\n"
        "👁 Без логов → Мы не следим за тобой\n"
        "📲 Устройства → Android, iPhone, ПК\n"
        "🎬 Контент → YouTube, Instagram без ограничений\n"
        "💬 Telegram → Работает даже при замедлении\n"
        "🔑 Просто → Один клик — и ты в сети\n"
        "🕰 Всегда → Работаем 24 часа 7 дней\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🛡 ТВОЯ БЕЗОПАСНОСТЬ:\n"
        "▪️ Реальный IP скрыт\n"
        "▪️ Данные не хранятся\n"
        "▪️ Соединение защищено\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📣 Канал с новостями: @tuvpn_news\n"
        "💬 Поддержка: @TuVPNSupport_bot\n\n"
        "🌊 TuVPN — свободный интернет для всех! 🚀",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "referral")
async def referral(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    ref_link = f"https://t.me/MaxArtVPN_bot?start={user_id}"

    # Личная статистика пользователя
    invited_total = 0
    invited_paid = 0
    bonus_days_balance = 0
    try:
        # Кого пригласил
        invited = sb.table("users").select("user_id").eq("referrer_id", user_id).execute()
        invited_total = len(invited.data or [])
        if invited.data:
            invited_ids = [u["user_id"] for u in invited.data]
            # Из них кто оплатил (есть успешный платёж)
            paid_check = sb.table("payments").select("user_id").in_("user_id", invited_ids).eq("status", "succeeded").execute()
            invited_paid = len(set(p["user_id"] for p in (paid_check.data or [])))
        # Bonus_days в копилке
        u_row = sb.table("users").select("bonus_days").eq("user_id", user_id).limit(1).execute()
        bonus_days_balance = (u_row.data[0].get("bonus_days") or 0) if u_row.data else 0
    except Exception as e:
        logging.error(f"referral stats error: {e}")

    stats_block = ""
    if invited_total > 0 or bonus_days_balance > 0:
        stats_block = (
            f"📊 <b>Ваша статистика:</b>\n"
            f"👥 Приглашено: <b>{invited_total}</b>"
        )
        if invited_total > 0:
            stats_block += f" (из них оплатили: {invited_paid})"
        stats_block += f"\n🎁 В копилке: <b>{bonus_days_balance} дн.</b>\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", switch_inline_query=ref_link)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])
    await callback.message.answer(
        f"🤝 <b>Позови друга — получи дни в подарок!</b>\n\n"
        f"{stats_block}"
        f"Твой друг получит <b>7 дней TuVPN бесплатно</b> 🎁\n\n"
        f"А ты получишь:\n"
        f"➕ <b>3 дня</b> — за переход друга по ссылке\n"
        f"➕ <b>7 дней</b> — за каждую оплату подписки другом\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"👆 Нажмите чтобы скопировать",
        reply_markup=kb,
        disable_web_page_preview=True
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "howto")
async def howto(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back")]])
    await callback.message.answer(
        "📲 <b>Как подключиться к TuVPN</b>\n\n"
        "Подключение занимает 2 минуты.\n"
        "Выберите своё устройство и следуйте инструкции:\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🍏 <b>iPhone / iPad</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ Установите приложение <b>Happ</b>\n"
        "👉 <a href=\"https://apps.apple.com/ru/app/happ-proxy-utility-plus/id6746188973\">Открыть в App Store</a>\n\n"
        "2️⃣ Вернитесь в бот → нажмите <b>«🔌 Подключиться»</b>\n\n"
        "3️⃣ Скопируйте ссылку подписки (она появится в сообщении)\n\n"
        "4️⃣ Откройте Happ → нажмите <b>➕</b> в правом верхнем углу\n\n"
        "5️⃣ Выберите <b>«Добавить из буфера обмена»</b>\n\n"
        "6️⃣ Нажмите большую круглую кнопку для подключения 🟢\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🤖 <b>Android</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ Установите приложение <b>v2RayTun</b>\n"
        "👉 <a href=\"https://play.google.com/store/apps/details?id=com.v2raytun.android\">Открыть в Google Play</a>\n\n"
        "2️⃣ Вернитесь в бот → нажмите <b>«🔌 Подключиться»</b>\n\n"
        "3️⃣ Скопируйте ссылку подписки\n\n"
        "4️⃣ Откройте v2RayTun → нажмите <b>➕</b>\n\n"
        "5️⃣ Выберите <b>«Импорт из буфера обмена»</b>\n\n"
        "6️⃣ Нажмите кнопку подключения 🟢\n\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "❓ <b>Что-то пошло не так?</b>\n"
        "Напишите нам в @TuVPNSupport_bot — поможем разобраться 🙌",
        reply_markup=kb,
        disable_web_page_preview=True
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "support")
async def support(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Написать в поддержку", url="https://t.me/TuVPNSupport_bot")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])
    await callback.message.answer(
        "🛠 <b>Помощь TuVPN</b>\n\n"
        "На связи и готовы решить любой вопрос — будь то проблемы с подключением, оплатой или просто совет.\n\n"
        "✉️ Напишите нам — ответим как можно скорее.\n\n"
        "👉 @TuVPNSupport_bot",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back")
async def back(callback: types.CallbackQuery):
    await callback.message.answer("Главное меню:", reply_markup=main_menu())
    await callback.answer()

async def main():
    from aiogram.types import BotCommand
    logging.basicConfig(level=logging.INFO)
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="menu", description="📋 Меню"),
    ])
    asyncio.create_task(check_expired())
    await dp.start_polling(bot)




@dp.callback_query(lambda c: c.data == "have_promo")
async def have_promo(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BuyStates.waiting_promo)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Без промокода", callback_data="no_promo")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_buy")],
    ])
    await callback.message.answer(
        "✍️ <b>Введите промокод</b>\n\n"
        "Введите код в сообщение ниже. Регистр не важен — мы приведём к верхнему автоматически.",
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "no_promo")
async def no_promo(callback: types.CallbackQuery, state: FSMContext):
    await _ask_email(callback.message, state)
    await callback.answer()


@dp.message(BuyStates.waiting_promo)
async def process_promo(message: types.Message, state: FSMContext):
    code_input = (message.text or "").strip().upper()
    user_id = message.from_user.id

    if not code_input or len(code_input) > 50:
        await message.answer("❌ Некорректный код. Попробуйте ещё раз.")
        return

    # Ищем промокод
    try:
        r = sb.table("promocodes").select("*").eq("code", code_input).limit(1).execute()
    except Exception as e:
        logging.error(f"Ошибка поиска промокода: {e}")
        await message.answer("⚠️ Сервис временно недоступен, попробуйте позже.")
        return

    if not r.data:
        await message.answer(
            "❌ <b>Промокод не найден</b>\n\n"
            "Проверьте правильность кода или продолжите без него.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Попробовать ещё раз", callback_data="have_promo")],
                [InlineKeyboardButton(text="➡️ Без промокода", callback_data="no_promo")],
                [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_buy")],
            ])
        )
        return

    promo = r.data[0]

    # Валидации
    if not promo.get("is_active"):
        await message.answer(
            "❌ Этот промокод деактивирован.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Другой промокод", callback_data="have_promo")],
                [InlineKeyboardButton(text="➡️ Без промокода", callback_data="no_promo")],
            ])
        )
        return

    if promo.get("expires_at"):
        try:
            from datetime import datetime as _dt
            exp = _dt.fromisoformat(promo["expires_at"].replace("Z", "+00:00"))
            if exp.tzinfo is not None:
                exp = exp.replace(tzinfo=None)
            if exp < _dt.now():
                await message.answer(
                    "❌ Срок действия промокода истёк.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🔁 Другой промокод", callback_data="have_promo")],
                        [InlineKeyboardButton(text="➡️ Без промокода", callback_data="no_promo")],
                    ])
                )
                return
        except Exception:
            pass

    if promo.get("max_uses") is not None and promo.get("uses_count", 0) >= promo["max_uses"]:
        await message.answer(
            "❌ Этот промокод уже исчерпан (достигнут лимит использований).",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Другой промокод", callback_data="have_promo")],
                [InlineKeyboardButton(text="➡️ Без промокода", callback_data="no_promo")],
            ])
        )
        return

    # Проверка: использовал ли уже этот пользователь
    used = sb.table("promocode_uses").select("id").eq("promocode_id", promo["id"]).eq("user_id", user_id).execute()
    if used.data:
        await message.answer(
            "❌ Вы уже использовали этот промокод ранее.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔁 Другой промокод", callback_data="have_promo")],
                [InlineKeyboardButton(text="➡️ Без промокода", callback_data="no_promo")],
            ])
        )
        return

    # Применяем промокод
    data = await state.get_data()
    base_price = data["price"]
    promo_type = promo["type"]
    promo_value = promo["value"]

    if promo_type == "percent":
        discount = round(base_price * promo_value / 100, 2)
        final_price = max(1, round(base_price - discount, 2))
        await state.update_data(
            promo_id=promo["id"], promo_code=promo["code"],
            promo_type=promo_type, promo_value=promo_value,
            final_price=final_price, bonus_days_from_promo=0,
        )
        text = (
            f"✅ <b>Промокод {promo['code']} применён!</b>\n\n"
            f"📦 {data['months_label']} / {data['devices']} уст.\n"
            f"💰 Цена: {base_price} ₽\n"
            f"🎁 Скидка {promo_value}%: −{discount} ₽\n"
            f"━━━━━━━━━━━━━━\n"
            f"💳 К оплате: <b>{final_price} ₽</b>\n\n"
            f"Продолжить?"
        )
    else:  # days
        await state.update_data(
            promo_id=promo["id"], promo_code=promo["code"],
            promo_type=promo_type, promo_value=promo_value,
            final_price=base_price, bonus_days_from_promo=promo_value,
        )
        text = (
            f"✅ <b>Промокод {promo['code']} применён!</b>\n\n"
            f"📦 {data['months_label']} / {data['devices']} уст.\n"
            f"💰 Цена: {base_price} ₽\n"
            f"🎁 Бонус: <b>+{promo_value} дней</b> к подписке\n\n"
            f"Продолжить?"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Продолжить", callback_data="promo_confirmed")],
        [InlineKeyboardButton(text="🔁 Другой промокод", callback_data="have_promo")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_buy")],
    ])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(lambda c: c.data == "promo_confirmed")
async def promo_confirmed(callback: types.CallbackQuery, state: FSMContext):
    await _ask_email(callback.message, state)
    await callback.answer()


# ══════════════════════════════
# ХЕНДЛЕРЫ УПРАВЛЕНИЯ УСТРОЙСТВАМИ  
# ══════════════════════════════

@dp.callback_query(lambda c: c.data == "connection_link")
async def connection_link(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    sub = get_subscription(user_id)
    
    if not sub:
        await callback.answer("❌ Подписка не найдена", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📲 Как настроить", callback_data="howto")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="connect")],
    ])
    
    await callback.message.answer(
        f"🔗 <b>Ваша ссылка для подключения:</b>\n"
        f"<code>{sub['sub_url']}</code>\n\n"
        f"👆 Нажмите на ссылку чтобы скопировать.\n\n"
        f"📲 Если впервые подключаетесь — нажмите «Как настроить».",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "my_devices")
async def my_devices(callback: types.CallbackQuery):
    from datetime import datetime as _dt, timezone as _tz
    user_id = callback.from_user.id
    devices = get_user_devices(user_id)
    sub = get_subscription(user_id)
    device_limit = sub.get("devices", 1) if sub else 1

    if not devices:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Получить ссылку подключения", callback_data="connection_link")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="connect")],
        ])
        await callback.message.answer(
            f"📱 <b>Мои устройства (0/{device_limit})</b>\n\n"
            f"🔍 У вас пока нет подключённых устройств.\n\n"
            f"Получите ссылку подписки и откройте её в Happ Plus или v2RayTun — ваше устройство автоматически появится в этом списке.",
            reply_markup=kb
        )
        await callback.answer()
        return

    def _fmt_ago(iso_str):
        if not iso_str:
            return "—"
        try:
            dt = _dt.fromisoformat(iso_str.replace("Z", "+00:00"))
            now = _dt.now(_tz.utc) if dt.tzinfo else _dt.now()
            diff = (now - dt).total_seconds()
            if diff < 60:
                return f"{int(diff)} сек назад"
            if diff < 3600:
                return f"{int(diff // 60)} мин назад"
            if diff < 86400:
                return f"{int(diff // 3600)} ч назад"
            return f"{int(diff // 86400)} дн назад"
        except Exception:
            return "—"

    # === HWID DEVICES UI 2026-05 ===
    def _fmt_date(iso_str):
        if not iso_str:
            return "—"
        try:
            dt = _dt.fromisoformat(iso_str.replace("Z", "+00:00"))
            return dt.strftime("%d.%m.%Y")
        except Exception:
            return "—"

    lines = [f"📱 <b>Мои устройства ({len(devices)}/{device_limit})</b>", ""]
    for i, d in enumerate(devices, 1):
        name = d.get("device_name") or "📱 Устройство"
        device_os = d.get("device_os") or ""
        os_version = d.get("os_version") or ""
        os_line = ""
        if device_os:
            os_line = f"{device_os}"
            if os_version:
                os_line += f" {os_version}"
        added = _fmt_date(d.get("connected_at"))
        last_seen = _fmt_ago(d.get("last_seen"))

        lines.append(f"<b>{i}.</b> {name}")
        detail = []
        if os_line:
            detail.append(f"📟 {os_line}")
        detail.append(f"📅 добавлено {added}")
        lines.append("   " + " · ".join(detail))
        lines.append(f"   🕐 активно: {last_seen}")
        lines.append("")

    lines.append("ℹ️ Если устройство больше не используется — удалите его, чтобы освободить слот.")

    device_buttons = []
    for d in devices:
        short_name = (d.get("device_name") or "Устройство").strip()[:25]
        device_buttons.append([
            InlineKeyboardButton(
                text=f"❌ Удалить · {short_name}",
                callback_data=f"remove_device_{d['id']}"
            )
        ])

    device_buttons.extend([
        [InlineKeyboardButton(text="🔗 Получить ссылку подключения", callback_data="connection_link")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="connect")],
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=device_buttons)
    await callback.message.answer("\n".join(lines), reply_markup=kb)
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("remove_device_"))
async def remove_device(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    device_id = int(callback.data.split("_")[2])
    
    try:
        device_r = sb.table("user_devices").select("device_name").eq("user_id", user_id).eq("id", device_id).execute()
        if not device_r.data:
            await callback.answer("❌ Устройство не найдено", show_alert=True)
            return
        
        device_name = device_r.data[0]['device_name']
        
        if remove_user_device(user_id, device_id):
            await callback.answer(f"✅ Устройство '{device_name}' удалено", show_alert=True)
            await my_devices(callback)
        else:
            await callback.answer("❌ Ошибка удаления устройства", show_alert=True)
    except Exception as e:
        logging.error(f"remove_device: {e}")
        await callback.answer("❌ Ошибка удаления устройства", show_alert=True)

@dp.callback_query(lambda c: c.data == "add_devices")
async def add_devices(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    sub = get_subscription(user_id)
    
    if not sub:
        await callback.answer("❌ Подписка не найдена", show_alert=True)
        return
    
    current_devices = count_active_devices(user_id)
    device_limit = sub.get('devices', 1)
    
    if current_devices >= device_limit:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Расширить подписку", callback_data="buy")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="my_devices")],
        ])
        
        await callback.message.answer(
            f"📱 <b>Добавить устройства</b>\n\n"
            f"⚠️ Вы используете все доступные слоты: <b>{current_devices}/{device_limit}</b>\n\n"
            f"Чтобы подключить больше устройств, расширьте подписку или удалите неиспользуемые устройства.",
            reply_markup=kb
        )
    else:
        available_slots = device_limit - current_devices
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Получить ссылку подключения", callback_data="connection_link")],
            [InlineKeyboardButton(text="🔄 Расширить подписку", callback_data="buy")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="my_devices")],
        ])
        
        await callback.message.answer(
            f"📱 <b>Добавить устройства</b>\n\n"
            f"✅ Доступно слотов: <b>{available_slots}</b>\n"
            f"📊 Использовано: <b>{current_devices}/{device_limit}</b>\n\n"
            f"Получите ссылку подключения и настройте новое устройство. Или расширьте подписку для большего количества устройств.",
            reply_markup=kb
        )
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "profile")
async def profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    stats = get_user_stats(user_id)
    
    if not stats:
        await callback.answer("❌ Ошибка загрузки профиля", show_alert=True)
        return
    
    user = stats['user']
    sub = stats['subscription']
    
    name_parts = []
    if user.get('first_name'):
        name_parts.append(user['first_name'])
    if user.get('last_name'):
        name_parts.append(user['last_name'])
    display_name = ' '.join(name_parts) if name_parts else f"ID {user_id}"
    
    username = f"@{user['username']}" if user.get('username') else "не указан"
    
    if sub:
        try:
            from datetime import datetime as _dt
            exp = _dt.fromisoformat(sub["expires_at"].replace("Z", "+00:00"))
            if exp.tzinfo is not None:
                exp = exp.replace(tzinfo=None)
            days_left = max(0, (exp - _dt.now()).days)
            
            if days_left > 0:
                sub_status = f"✅ Активна до {exp.strftime('%d.%m.%Y')} ({days_left} дн.)"
                device_info = f"📱 Устройств: {stats['devices_count']}/{sub.get('devices', 1)}"
            else:
                sub_status = f"⚠️ Истекла {exp.strftime('%d.%m.%Y')}"
                device_info = f"📱 Лимит устройств: {sub.get('devices', 1)}"
        except:
            sub_status = "❓ Ошибка определения статуса"
            device_info = f"📱 Лимит устройств: {sub.get('devices', 1)}"
    else:
        sub_status = "❌ Нет активной подписки"
        device_info = "📱 Устройств: 0"
    
    bonus_days = user.get('bonus_days', 0)
    balance_info = f"💰 Бонусных дней: {bonus_days}" if bonus_days > 0 else "💰 Бонусных дней: нет"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Подключиться", callback_data="connect")],
        [InlineKeyboardButton(text="🛒 Оформить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="🤝 Пригласить друга", callback_data="referral")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])
    
    await callback.message.answer(
        f"👤 <b>Профиль пользователя</b>\n\n"
        f"👨‍💻 <b>{display_name}</b>\n"
        f"🆔 {username}\n"
        f"🔢 ID: <code>{user_id}</code>\n\n"
        f"🔐 <b>Подписка:</b>\n"
        f"{sub_status}\n"
        f"{device_info}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"💳 Платежей: {stats['payments_count']}\n"
        f"💸 Потрачено: {stats['total_paid']:.0f} ₽\n"
        f"👥 Приглашено: {stats['referrals_count']} друзей\n"
        f"{balance_info}",
        reply_markup=kb
    )
    await callback.answer()




# === ADMIN LOGIN HANDLER ===
import secrets as _admin_secrets
try:
    from config import ADMIN_TG_IDS, ADMIN_SESSION_DAYS
except ImportError:
    ADMIN_TG_IDS = [784871620, 1027228622]
    ADMIN_SESSION_DAYS = 7


@dp.callback_query(lambda c: c.data and c.data.startswith("adm_login_confirm:"))
async def cb_admin_login_confirm(call: types.CallbackQuery):
    """Юзер нажал «Подтвердить вход в админку»."""
    login_token = call.data.split(":", 1)[1]
    tg_id = call.from_user.id

    # Whitelist проверка
    if tg_id not in ADMIN_TG_IDS:
        await call.answer("❌ Доступ запрещён", show_alert=True)
        return

    # Проверяем что попытка ещё валидна
    try:
        r = sb.table("admin_login_attempts").select("*").eq("login_token", login_token).limit(1).execute()
        if not r.data:
            await call.answer("❌ Сессия логина не найдена", show_alert=True)
            return
        att = r.data[0]
        if att["status"] != "pending":
            await call.answer(f"⚠ Эта ссылка уже использована (status: {att['status']})", show_alert=True)
            return
        # Проверим истечение
        try:
            from datetime import datetime as _dt
            exp = _dt.fromisoformat(att["expires_at"].replace("Z", "+00:00")).replace(tzinfo=None)
            if exp <= _dt.utcnow():
                sb.table("admin_login_attempts").update({"status": "expired"}).eq("login_token", login_token).execute()
                await call.answer("⏱ Срок ссылки истёк, начните вход заново", show_alert=True)
                return
        except Exception:
            pass

        # Генерим session_token и создаём сессию
        from datetime import datetime as _dt, timedelta as _td
        session_token = _admin_secrets.token_urlsafe(48)
        session_exp = _dt.utcnow() + _td(days=ADMIN_SESSION_DAYS)
        sb.table("admin_sessions").insert({
            "session_token": session_token,
            "tg_id": tg_id,
            "tg_username": call.from_user.username or "",
            "expires_at": session_exp.isoformat(),
            "ip_address": att.get("ip_address") or "",
            "user_agent": att.get("user_agent") or "",
        }).execute()

        # Обновляем попытку логина
        sb.table("admin_login_attempts").update({
            "status": "confirmed",
            "tg_id": tg_id,
            "tg_username": call.from_user.username or "",
            "session_token": session_token,
            "confirmed_at": _dt.utcnow().isoformat(),
        }).eq("login_token", login_token).execute()

        await call.message.edit_text(
            "✅ <b>Вход в админку подтверждён</b>\n\n"
            "Вернитесь во вкладку браузера — админка откроется автоматически в течение пары секунд.\n\n"
            f"🕐 Сессия действует {ADMIN_SESSION_DAYS} дней.",
            parse_mode="HTML",
        )
        await call.answer("Вход подтверждён!")
    except Exception as e:
        logging.error(f"admin login confirm error: {e}")
        await call.answer(f"Ошибка: {e}", show_alert=True)


@dp.callback_query(lambda c: c.data and c.data.startswith("adm_login_cancel:"))
async def cb_admin_login_cancel(call: types.CallbackQuery):
    login_token = call.data.split(":", 1)[1]
    try:
        sb.table("admin_login_attempts").update({"status": "rejected"}).eq("login_token", login_token).execute()
    except Exception:
        pass
    try:
        await call.message.edit_text("❌ Вход отклонён. Если это не вы пытались войти — никаких действий не требуется.")
    except Exception:
        pass
    await call.answer("Отклонено")


# === END ADMIN LOGIN HANDLER ===


if __name__ == "__main__":
    asyncio.run(main())
