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
    try:
        sub = get_subscription(user_id)
        user = get_user(user_id)
        client_uuid = user.get("client_uuid") if user else None
        if sub:
            new_expires = extend_db_subscription(sub["id"], user_id, days)
            if client_uuid and new_expires:
                remaining = max(1, (new_expires - datetime.now()).days)
                await xui_extend_client(client_uuid, user_id, sub["devices"], remaining)
        await bot.send_message(user_id,
            f"🎁 Вам начислено {days} дней бонуса!\nПричина: {reason}"
        )
    except Exception as e:
        logging.error(f"give_referral_bonus: {e}")

async def give_new_user_bonus(user_id, days=7):
    try:
        client_uuid, sub_url = await xui_add_client(user_id, 1, days)
        if client_uuid:
            create_db_subscription(user_id, 1, days, client_uuid, sub_url)
            await bot.send_message(user_id,
                f"🎁 Вам начислено {days} дней бесплатного доступа!\n\n"
                f"Ваша ссылка подписки:\n{sub_url}\n\n"
                f"Нажмите /start для подключения!"
            )
    except Exception as e:
        logging.error(f"give_new_user_bonus: {e}")

# ══════════════════════════════
# ПРОВЕРКА ИСТЁКШИХ ПОДПИСОК
# ══════════════════════════════
async def check_expired():
    while True:
        try:
            r = sb.table("subscriptions").select("*").eq("status", "active").execute()
            now = datetime.now()
            for sub in r.data:
                expires = datetime.fromisoformat(sub["expires_at"])
                if now > expires:
                    deactivate_subscription(sub["id"])
                    user = get_user(sub["user_id"])
                    client_uuid = user.get("client_uuid") if user else None
                    if client_uuid:
                        await xui_toggle_client(client_uuid, sub["user_id"], False, sub.get("devices", 1))
                    try:
                        await bot.send_message(sub["user_id"],
                            "⚠️ Ваша подписка TuVPN истекла.\n\nПродлите подписку чтобы восстановить доступ!",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🛒 Продлить", callback_data="buy")]
                            ])
                        )
                    except:
                        pass
        except Exception as e:
            logging.error(f"check_expired: {e}")
        await asyncio.sleep(3600)

# ══════════════════════════════
# ЦЕНЫ
# ══════════════════════════════
PRICES = {
    1: {"1": 149, "3": 399, "12": 1399},
    2: {"1": 249, "3": 649, "12": 2299},
    5: {"1": 599, "3": 1599, "12": 5499},
}
DAYS = {"1": 30, "3": 90, "12": 365}

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Подключиться", callback_data="connect")],
        [InlineKeyboardButton(text="🛒 Оформить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="📋 Как подключиться", callback_data="howto"),
         InlineKeyboardButton(text="🤝 Позвать друга", callback_data="referral")],
        [InlineKeyboardButton(text="📣 Наш канал", callback_data="channel")],
        [InlineKeyboardButton(text="🔎 О сервисе", callback_data="about"),
         InlineKeyboardButton(text="🛠 Помощь", callback_data="support")],
    ])

@dp.message(Command("start"))
async def start(message: types.Message):
    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    user_id = message.from_user.id
    first_name = message.from_user.first_name or ""

    is_new = register_user(user_id, message.from_user.username,
                           first_name, message.from_user.last_name, referrer_id)

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
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📲 Как настроить", callback_data="howto")],
                [InlineKeyboardButton(text="🔄 Продлить / изменить тариф", callback_data="buy")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
            ])
            text = (
                f"🔌 <b>Подключение к TuVPN</b>\n\n"
                f"✅ Подписка активна\n"
                f"📅 До: <b>{exp.strftime('%d.%m.%Y')}</b> (осталось {days_left} дн.)\n"
                f"📱 Тариф: <b>{sub['devices']} устр.</b>\n\n"
                f"🔗 <b>Ваша ссылка для подключения:</b>\n"
                f"<code>{sub['sub_url']}</code>\n\n"
                f"👆 Нажмите на ссылку чтобы скопировать.\n\n"
                f"📲 Если впервые подключаетесь — нажмите «Как настроить»."
            )
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Продлить подписку", callback_data="buy")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
            ])
            text = (
                f"🔌 <b>Подключение к TuVPN</b>\n\n"
                f"⚠️ Ваша подписка <b>истекла</b> {exp.strftime('%d.%m.%Y')}\n\n"
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
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Банковская карта РФ", callback_data=f"pay_card_{devices}_{months}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=f"devices_{devices}")],
    ])
    await callback.message.answer(
        f"📋 Оплата подписки\n\n"
        f"📦 {months_label} / {devices} уст. / {price} ₽ / {days} дней\n\n"
        f"Выберите способ оплаты:",
        reply_markup=kb
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
    """Запрашивает email у пользователя для чека.
    Должна вызываться ПОСЛЕ обработки промокода (или его пропуска)."""
    data = await state.get_data()
    devices = data.get("devices")
    months_label = data.get("months_label")
    final_price = data.get("final_price", data.get("price"))
    promo_code = data.get("promo_code")
    bonus_days = data.get("bonus_days_from_promo", 0)

    promo_line = ""
    if promo_code:
        promo_type = data.get("promo_type")
        if promo_type == "percent":
            promo_line = f"\n🎁 Промокод <b>{promo_code}</b>: скидка {data.get('promo_value')}%"
        elif promo_type == "days":
            promo_line = f"\n🎁 Промокод <b>{promo_code}</b>: +{bonus_days} дней"

    await state.set_state(BuyStates.waiting_email)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_buy")],
    ])
    await message.answer(
        f"📧 <b>Введите ваш email для отправки чека</b>\n\n"
        f"📦 {months_label} / {devices} уст.{promo_line}\n"
        f"💰 К оплате: <b>{final_price} ₽</b>\n\n"
        f"Чек будет отправлен на указанный email.",
        reply_markup=kb,
    )


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
    await callback.answer("📣 Наш канал появится совсем скоро!", show_alert=True)

@dp.callback_query(lambda c: c.data == "about")
async def about(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back")]])
    await callback.message.answer(
        "🌊 TuVPN — твой надёжный щит в сети\n\n"
        "Стабильный • Быстрый • Безопасный\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "💎 ПОЧЕМУ TUVPN:\n"
        "🏎 Скорость → Без тормозов и просадок\n"
        "🌍 Серверы: Финляндия 🇫🇮\n"
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


if __name__ == "__main__":
    asyncio.run(main())
