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
    is_new = register_user(message.from_user.id, message.from_user.username,
                           message.from_user.first_name, message.from_user.last_name, referrer_id)
    if is_new and referrer_id and referrer_id != message.from_user.id:
        try:
            sb.table("referrals").insert({"referrer_id": referrer_id, "referred_id": message.from_user.id}).execute()
            await give_new_user_bonus(message.from_user.id, 7)
            await give_referral_bonus(referrer_id, 3, "Друг перешёл по вашей ссылке")
        except Exception as e:
            logging.error(f"referral processing: {e}")
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
            f"Ваша ссылка подписки:\n{sub['sub_url']}\n\n"
            f"🛠 Поддержка: @TuVPNSupport_bot\n\n"
            f"Нажмите Подключить VPN и следуйте инструкции"
        )
    else:
        text = (
            f"👤 ID: {callback.from_user.id}\n"
            f"📊 Статус: не активна\n\n"
            f"У вас нет активной подписки.\n"
            f"Оформите подписку чтобы получить доступ!\n\n"
            f"🛠 Поддержка: @TuVPNSupport_bot"
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
    await callback.message.answer(
        f"📱 Ваши устройства\n\nПодключено устройств: {sub['devices'] if sub else 0}\n\nХотите больше?",
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
        [InlineKeyboardButton(text=f"🗓 1 месяц / {devices} уст. — {p['1']} ₽", callback_data=f"period_{devices}_1")],
        [InlineKeyboardButton(text=f"📆 3 месяца / {devices} уст. — {p['3']} ₽", callback_data=f"period_{devices}_3")],
        [InlineKeyboardButton(text=f"🏆 1 год / {devices} уст. — {p['12']} ₽", callback_data=f"period_{devices}_12")],
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
async def pay_card(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    devices = int(parts[2])
    months = parts[3]
    price = PRICES[devices][months]
    months_label = {"1": "1 месяц", "3": "3 месяца", "12": "1 год"}[months]

    # Запоминаем выбор пользователя в state
    await state.set_state(BuyStates.waiting_email)
    await state.update_data(devices=devices, months=months, price=price, months_label=months_label)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_buy")],
    ])
    await callback.message.answer(
        f"📧 Введите ваш email для отправки чека\n\n"
        f"📦 {months_label} / {devices} уст. / {price} ₽\n\n"
        f"Чек будет отправлен на указанный email.",
        reply_markup=kb,
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "cancel_buy")
async def cancel_buy(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Покупка отменена. Главное меню — /start")
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
    price = data["price"]
    months_label = data["months_label"]

    user_id = message.from_user.id
    description = f"TuVPN: {months_label}, {devices} уст."

    try:
        payment = yookassa_client.create_payment(
            amount=price,
            description=description,
            user_id=user_id,
            devices=devices,
            months=int(months),
            email=email,
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
        sb.table("payments").insert({
            "provider": "yookassa",
            "provider_payment_id": payment["payment_id"],
            "user_id": user_id,
            "amount": price,
            "currency": "RUB",
            "status": payment["status"],
            "email": email,
            "devices": devices,
            "months": int(months),
            "description": description,
            "confirmation_url": payment["confirmation_url"],
        }).execute()
    except Exception as e:
        logging.error(f"Не удалось записать платёж в БД: {e}")

    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=payment["confirmation_url"])],
    ])
    await message.answer(
        f"✅ Платёж создан!\n\n"
        f"📦 {months_label} / {devices} уст.\n"
        f"💰 Сумма: {price} ₽\n"
        f"📧 Email для чека: {email}\n\n"
        f"Нажмите кнопку ниже, чтобы оплатить.\n"
        f"После успешной оплаты ссылка для подключения появится в боте в разделе «🔌 Подключиться».",
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back")]])
    await callback.message.answer(
        "📲 <b>Как подключиться к TuVPN</b>\n\n"
        "Подключение занимает 2 минуты.\n"
        "Выберите своё устройство и следуйте инструкции:\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🍏 <b>iPhone / iPad</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ Установите приложение <b>Happ</b>\n"
        "👉 <a href=\"https://apps.apple.com/app/happ-proxy-utility/id6504287215\">Открыть в App Store</a>\n\n"
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
        "🛠 Помощь TuVPN\n\n"
        "На связи и готовы решить любой вопрос!\n\n"
        "✉️ Пиши — отвечаем быстро\n"
        "⏱ Среднее время ответа: до 1 часа\n\n"
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

if __name__ == "__main__":
    asyncio.run(main())
