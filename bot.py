import asyncio
import logging
import uuid
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from supabase import create_client
from config import *

bot = Bot(token=BOT_TOKEN)
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
        logging.error(f"get_user error: {e}")
        return None

def register_user(user_id, username, first_name=None, last_name=None, referrer_id=None):
    try:
        existing = get_user(user_id)
        if not existing:
            data = {"user_id": user_id, "username": username or "", "first_name": first_name or "", "last_name": last_name or ""}
            if referrer_id:
                data["referrer_id"] = referrer_id
            sb.table("users").insert(data).execute()
            return True  # новый пользователь
        return False
    except Exception as e:
        logging.error(f"register_user error: {e}")
        return False

def get_subscription(user_id):
    try:
        r = sb.table("subscriptions").select("*").eq("user_id", user_id).eq("status", "active").execute()
        return r.data[0] if r.data else None
    except Exception as e:
        logging.error(f"get_subscription error: {e}")
        return None

def create_subscription(user_id, devices, days, client_uuid, sub_url):
    try:
        expires = datetime.now() + timedelta(days=days)
        sb.table("subscriptions").insert({
            "user_id": user_id,
            "devices": devices,
            "status": "active",
            "sub_url": sub_url,
            "started_at": datetime.now().isoformat(),
            "expires_at": expires.isoformat()
        }).execute()
        sb.table("users").update({"client_uuid": client_uuid}).eq("user_id", user_id).execute()
        return expires
    except Exception as e:
        logging.error(f"create_subscription error: {e}")
        return None

def extend_subscription(sub_id, user_id, days):
    try:
        sub = get_subscription(user_id)
        if sub:
            current_expires = datetime.fromisoformat(sub["expires_at"])
            new_expires = max(current_expires, datetime.now()) + timedelta(days=days)
            sb.table("subscriptions").update({
                "expires_at": new_expires.isoformat(),
                "status": "active"
            }).eq("id", sub_id).execute()
            return new_expires
        return None
    except Exception as e:
        logging.error(f"extend_subscription error: {e}")
        return None

def deactivate_subscription(sub_id):
    try:
        sb.table("subscriptions").update({"status": "inactive"}).eq("id", sub_id).execute()
    except Exception as e:
        logging.error(f"deactivate error: {e}")

# ══════════════════════════════
# 3X-UI API
# ══════════════════════════════
PANEL_BASE = f"{PANEL_URL}"
XUI_PATH = "/xui/API/inbounds"

async def get_xui_session():
    connector = aiohttp.TCPConnector(ssl=False)
    session = aiohttp.ClientSession(connector=connector)
    await session.post(f"{PANEL_BASE}/login", json={
        "username": PANEL_USER, "password": PANEL_PASS
    })
    return session

async def create_xui_client(user_id, devices, days):
    """Создаёт уникального клиента в 3X-UI и возвращает (uuid, sub_url)"""
    client_uuid = str(uuid.uuid4())
    email = f"user_{user_id}"
    expire_ms = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)

    session = await get_xui_session()
    try:
        payload = {
            "id": INBOUND_ID,
            "settings": f'{{"clients":[{{"id":"{client_uuid}","email":"{email}","limitIp":{devices},"totalGB":0,"expiryTime":{expire_ms},"enable":true,"flow":"xtls-rprx-vision","comment":""}}]}}'
        }
        resp = await session.post(f"{PANEL_BASE}{XUI_PATH}/addClient", json=payload)
        data = await resp.json()
        await session.close()

        if data.get("success"):
            # Формируем уникальную ссылку подписки для этого пользователя
            sub_url = f"https://{SERVER_IP}:8443/sub.txt?uuid={client_uuid}"
            return client_uuid, sub_url
        else:
            logging.error(f"XUI addClient failed: {data}")
    except Exception as e:
        logging.error(f"create_xui_client error: {e}")
        await session.close()
    return None, None

async def toggle_xui_client(client_uuid, user_id, enable, devices=1):
    """Включает или выключает клиента"""
    email = f"user_{user_id}"
    session = await get_xui_session()
    try:
        payload = {
            "id": INBOUND_ID,
            "settings": f'{{"clients":[{{"id":"{client_uuid}","email":"{email}","limitIp":{devices},"enable":{str(enable).lower()},"flow":"xtls-rprx-vision"}}]}}'
        }
        await session.post(f"{PANEL_BASE}{XUI_PATH}/updateClient/{client_uuid}", json=payload)
    except Exception as e:
        logging.error(f"toggle_xui_client error: {e}")
    await session.close()

async def extend_xui_client(client_uuid, user_id, devices, days):
    """Продлевает дату окончания клиента"""
    email = f"user_{user_id}"
    expire_ms = int((datetime.now() + timedelta(days=days)).timestamp() * 1000)
    session = await get_xui_session()
    try:
        payload = {
            "id": INBOUND_ID,
            "settings": f'{{"clients":[{{"id":"{client_uuid}","email":"{email}","limitIp":{devices},"expiryTime":{expire_ms},"enable":true,"flow":"xtls-rprx-vision"}}]}}'
        }
        await session.post(f"{PANEL_BASE}{XUI_PATH}/updateClient/{client_uuid}", json=payload)
    except Exception as e:
        logging.error(f"extend_xui_client error: {e}")
    await session.close()

# ══════════════════════════════
# РЕФЕРАЛЬНАЯ СИСТЕМА
# ══════════════════════════════
async def process_referral_bonus(referrer_id, bonus_days, reason):
    """Начисляет бонусные дни рефереру"""
    try:
        sub = get_subscription(referrer_id)
        if sub:
            user = get_user(referrer_id)
            client_uuid = user.get("client_uuid") if user else None
            devices = sub.get("devices", 1)
            new_expires = extend_subscription(sub["id"], referrer_id, bonus_days)
            if client_uuid and new_expires:
                remaining = (new_expires - datetime.now()).days
                await extend_xui_client(client_uuid, referrer_id, devices, remaining)
            await bot.send_message(
                referrer_id,
                f"🎁 Вам начислено {bonus_days} дней за реферала!\n\n"
                f"Причина: {reason}\n"
                f"Подписка продлена до: {new_expires.strftime('%d.%m.%Y') if new_expires else '—'}"
            )
        else:
            # Нет активной подписки — создаём запись о будущем бонусе
            # (применится при следующей покупке)
            logging.info(f"Referrer {referrer_id} has no active sub, bonus {bonus_days}d pending")
    except Exception as e:
        logging.error(f"process_referral_bonus error: {e}")

async def give_new_user_bonus(user_id, bonus_days=7):
    """Даёт новому пользователю пришедшему по рефералке бесплатные дни"""
    try:
        client_uuid, sub_url = await create_xui_client(user_id, 1, bonus_days)
        if client_uuid:
            create_subscription(user_id, 1, bonus_days, client_uuid, sub_url)
            await bot.send_message(
                user_id,
                f"🎁 Вам начислено {bonus_days} дней бесплатного доступа TuVPN!\n\n"
                f"Ваша ссылка подписки:\n`{sub_url}`\n\n"
                f"📋 Нажмите /start и следуйте инструкции для подключения!"
            )
    except Exception as e:
        logging.error(f"give_new_user_bonus error: {e}")

# ══════════════════════════════
# ПРОВЕРКА ИСТЁКШИХ ПОДПИСОК
# ══════════════════════════════
async def check_expired():
    while True:
        try:
            r = sb.table("subscriptions").select("*, users(client_uuid, devices)").eq("status", "active").execute()
            now = datetime.now()
            for sub in r.data:
                expires = datetime.fromisoformat(sub["expires_at"])
                if now > expires:
                    deactivate_subscription(sub["id"])
                    user_data = sub.get("users", {})
                    client_uuid = user_data.get("client_uuid") if user_data else None
                    devices = user_data.get("devices", 1) if user_data else 1
                    if client_uuid:
                        await toggle_xui_client(client_uuid, sub["user_id"], False, devices)
                    try:
                        await bot.send_message(
                            sub["user_id"],
                            "⚠️ Ваша подписка TuVPN истекла.\n\n"
                            "Продлите подписку чтобы восстановить доступ!",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🛒 Продлить подписку", callback_data="buy")]
                            ])
                        )
                    except:
                        pass
        except Exception as e:
            logging.error(f"check_expired error: {e}")
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

# ══════════════════════════════
# МЕНЮ
# ══════════════════════════════
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

# ══════════════════════════════
# HANDLERS
# ══════════════════════════════
@dp.message(Command("start"))
async def start(message: types.Message):
    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None

    is_new = register_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
        referrer_id
    )

    # Реферальная логика
    if is_new and referrer_id and referrer_id != message.from_user.id:
        try:
            # Записываем реферала
            sb.table("referrals").insert({
                "referrer_id": referrer_id,
                "referred_id": message.from_user.id
            }).execute()
            # Новый пользователь получает 7 дней бесплатно
            await give_new_user_bonus(message.from_user.id, 7)
            # Реферер получает 3 дня за переход
            await process_referral_bonus(referrer_id, 3, "Друг перешёл по вашей ссылке")
        except Exception as e:
            logging.error(f"Referral processing error: {e}")

    await message.answer(
        "Привет! 🖐\n\n"
        "🌊 TuVPN — просто включи и пользуйся.\n\n"
        "⚡️ Работает сразу после оплаты\n"
        "💰 Честные цены без переплат\n"
        "🎬 Instagram, YouTube, Telegram — всё открыто",
        reply_markup=main_menu()
    )

@dp.message(Command("menu"))
async def menu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu())

@dp.callback_query(lambda c: c.data == "connect")
async def connect(callback: types.CallbackQuery):
    sub = get_subscription(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Подключить VPN", callback_data="howto")],
        [InlineKeyboardButton(text="🛒 Продлить / Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="📱 Мои устройства", callback_data="my_devices")],
        [InlineKeyboardButton(text="🏠 На старт", callback_data="back")],
    ])
    if sub:
        expires = datetime.fromisoformat(sub["expires_at"]).strftime("%d.%m.%Y")
        text = (
            f"Подписка активна до: {expires}\n\n"
            f"👤 ID: {callback.from_user.id}\n"
            f"📊 Статус: активна\n"
            f"📱 Устройств: {sub['devices']}\n\n"
            f"Ваша ссылка подписки:\n"
            f"`{sub['sub_url']}`\n\n"
            f"🛠 Поддержка: @TuVPN_support\n\n"
            f"Нажмите Подключить VPN и следуйте инструкции"
        )
    else:
        text = (
            f"👤 ID: {callback.from_user.id}\n"
            f"📊 Статус: не активна\n\n"
            f"У вас нет активной подписки.\n"
            f"Оформите подписку чтобы получить доступ!\n\n"
            f"🛠 Поддержка: @TuVPN_support"
        )
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "my_devices")
async def my_devices(callback: types.CallbackQuery):
    sub = get_subscription(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить устройства", callback_data="buy")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="connect")],
    ])
    devices = sub["devices"] if sub else 0
    await callback.message.answer(
        f"📱 Ваши устройства\n\nПодключено устройств: {devices}\n\nХотите добавить больше?",
        reply_markup=kb
    )
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
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🗓 1 месяц  /  {devices} уст.  —  {p['1']} ₽", callback_data=f"period_{devices}_1")],
        [InlineKeyboardButton(text=f"📆 3 месяца  /  {devices} уст.  —  {p['3']} ₽", callback_data=f"period_{devices}_3")],
        [InlineKeyboardButton(text=f"🏆 1 год  /  {devices} уст.  —  {p['12']} ₽", callback_data=f"period_{devices}_12")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")],
    ])
    await callback.message.answer(
        f"🌊 Оформление подписки TuVPN\n\n🔹 Устройств: {devices}\nВыберите период:",
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
async def pay_card(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    devices = int(parts[2])
    months = parts[3]
    price = PRICES[devices][months]
    months_label = {"1": "1 месяц", "3": "3 месяца", "12": "1 год"}[months]
    await callback.answer(
        f"⏳ Оплата картой скоро будет доступна!\n\nПока напишите в поддержку: @TuVPN_support",
        show_alert=True
    )

@dp.callback_query(lambda c: c.data == "channel")
async def channel(callback: types.CallbackQuery):
    await callback.answer("📣 Наш канал появится совсем скоро!", show_alert=True)

@dp.callback_query(lambda c: c.data == "about")
async def about(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])
    await callback.message.answer(
        "🌊 TuVPN — твой надёжный щит в сети\n\n"
        "Стабильный • Быстрый • Безопасный\n\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "💎 ПОЧЕМУ TUVPN:\n"
        "🏎 Скорость → Без тормозов и просадок\n"
        "🌍 Серверы → Европа, стабильный пинг\n"
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
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой", switch_inline_query=ref_link)],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])
    await callback.message.answer(
        "🤝 Позови друга — получи дни в подарок!\n\n"
        "Твой друг получит 7 дней TuVPN бесплатно 🎁\n\n"
        "А ты получишь:\n"
        "➕ 3 дня — за переход друга по ссылке\n"
        "➕ 7 дней — за каждую оплату подписки другом\n\n"
        f"🔗 Твоя ссылка:\n`{ref_link}`",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "howto")
async def howto(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])
    await callback.message.answer(
        "📋 Как подключиться к TuVPN\n\n"
        "🍏 iPhone:\n"
        "1. Скачай Happ Plus — App Store\n"
        "2. Зайди в бота → нажми Подключиться\n"
        "3. Скопируй ссылку подписки\n"
        "4. В Happ Plus: + → Добавить по URL\n"
        "5. Вставь ссылку → готово!\n\n"
        "🤖 Android:\n"
        "1. Скачай v2rayTun — Play Store\n"
        "2. Зайди в бота → нажми Подключиться\n"
        "3. Скопируй ссылку подписки\n"
        "4. В v2rayTun: + → Импорт по ссылке\n"
        "5. Вставь ссылку → готово!\n\n"
        "🆘 Не выходит? Пиши — поможем!\n"
        "@TuVPN_support",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "support")
async def support(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Написать в поддержку", url="https://t.me/TuVPN_support")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")],
    ])
    await callback.message.answer(
        "🛠 Помощь TuVPN\n\n"
        "На связи и готовы решить любой вопрос!\n\n"
        "✉️ Напиши нам — ответим быстро\n"
        "⏱ Среднее время ответа: до 1 часа\n\n"
        "👉 @TuVPN_support",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back")
async def back(callback: types.CallbackQuery):
    await callback.message.answer("Главное меню:", reply_markup=main_menu())
    await callback.answer()

async def main():
    logging.basicConfig(level=logging.INFO)
    asyncio.create_task(check_expired())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
