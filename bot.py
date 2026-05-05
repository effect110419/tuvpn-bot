import asyncio
import logging
import sqlite3
import uuid
import aiohttp
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = "8752254235:AAGB0u5p4BHlCYU1IMTWpte_Un2HaefF_vE"
PANEL_URL = "https://89.125.53.210:17627/I4z8tB7MLF8wPjpKDW"
PANEL_USER = "clmHydSJD6"
PANEL_PASS = "otfCjziZyn"
INBOUND_ID = 2

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def init_db():
    conn = sqlite3.connect('/root/tuvpn.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        sub_url TEXT,
        devices INTEGER DEFAULT 1,
        status TEXT DEFAULT 'inactive',
        expires TEXT,
        client_uuid TEXT
    )''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('/root/tuvpn.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id=?', (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def register_user(user_id, username):
    conn = sqlite3.connect('/root/tuvpn.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)',
              (user_id, username or ""))
    conn.commit()
    conn.close()

def deactivate_user(user_id):
    conn = sqlite3.connect('/root/tuvpn.db')
    c = conn.cursor()
    c.execute('UPDATE users SET status="inactive" WHERE user_id=?', (user_id,))
    conn.commit()
    conn.close()

async def check_expired():
    while True:
        try:
            conn = sqlite3.connect('/root/tuvpn.db')
            c = conn.cursor()
            c.execute("SELECT user_id, client_uuid FROM users WHERE status='active'")
            users = c.fetchall()
            conn.close()
            now = datetime.now()
            for user_id, client_uuid in users:
                user = get_user(user_id)
                if user and user[5]:
                    try:
                        expires = datetime.strptime(user[5], "%d.%m.%Y")
                        if now > expires:
                            deactivate_user(user_id)
                            try:
                                await bot.send_message(user_id,
                                    "⚠️ Ваша подписка TuVPN истекла.\n\n"
                                    "Продлите подписку чтобы восстановить доступ!",
                                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                        [InlineKeyboardButton(text="🛒 Продлить", callback_data="buy")]
                                    ])
                                )
                            except:
                                pass
                    except:
                        pass
        except Exception as e:
            logging.error(f"Check expired error: {e}")
        await asyncio.sleep(3600)

PRICES = {
    1: {"1": 149, "3": 399, "12": 1399},
    2: {"1": 249, "3": 649, "12": 2299},
    5: {"1": 599, "3": 1599, "12": 5499},
}

def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡️ Подключиться", callback_data="connect")],
        [InlineKeyboardButton(text="🛒 Оформить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="📋 Как подключиться", callback_data="howto"),
         InlineKeyboardButton(text="🤝 Позвать друга", callback_data="referral")],
        [InlineKeyboardButton(text="📣 Наш канал", callback_data="soon")],
        [InlineKeyboardButton(text="🔎 О сервисе", callback_data="about"),
         InlineKeyboardButton(text="🛠 Помощь", callback_data="support")],
    ])

@dp.message(Command("start"))
async def start(message: types.Message):
    register_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "Привет! 🖐\n\n"
        "🌊 TuVPN — просто включи и пользуйся.\n\n"
        "⚡️ Работает сразу после оплаты\n"
        "💰 Честные цены без переплат\n"
        "🎬 Instagram, YouTube — всё открыто",
        reply_markup=main_menu()
    )

@dp.message(Command("menu"))
async def menu(message: types.Message):
    await message.answer("Главное меню:", reply_markup=main_menu())

@dp.callback_query(lambda c: c.data == "connect")
async def connect(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Подключить VPN", callback_data="howto")],
        [InlineKeyboardButton(text="🛒 Продлить / Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="📱 Мои устройства", callback_data="my_devices")],
        [InlineKeyboardButton(text="🏠 На старт", callback_data="back")],
    ])
    # user = (user_id, username, sub_url, devices, status, expires, client_uuid)
    #           0        1        2        3         4       5        6
    if user and user[4] == 'active':
        expires = user[5] or "—"
        devices = user[3] or 1
        sub_url = user[2] or "—"
        text = (
            f"Ваша подписка активна до: {expires}\n\n"
            f"👤 ID: {callback.from_user.id}\n"
            f"📊 Статус: активна\n"
            f"📱 Устройств: {devices}\n\n"
            f"Ваша ссылка подписки:\n"
            f"`{sub_url}`\n\n"
            f"🛠 Поддержка: @MaxArtVPN_bot\n\n"
            f"Нажмите Подключить VPN и следуйте инструкции"
        )
    else:
        text = (
            f"👤 ID: {callback.from_user.id}\n"
            f"📊 Статус: не активна\n\n"
            f"У вас нет активной подписки.\n"
            f"Оформите подписку чтобы получить доступ!\n\n"
            f"🛠 Поддержка: @MaxArtVPN_bot"
        )
    await callback.message.answer(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "my_devices")
async def my_devices(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить устройства", callback_data="buy")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="connect")],
    ])
    devices = user[3] if user else 1
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
        [InlineKeyboardButton(text=f"🗓 1 месяц  /  {devices} уст.  —  {p['1']} ₽", callback_data="soon")],
        [InlineKeyboardButton(text=f"📆 3 месяца  /  {devices} уст.  —  {p['3']} ₽", callback_data="soon")],
        [InlineKeyboardButton(text=f"🏆 1 год  /  {devices} уст.  —  {p['12']} ₽", callback_data="soon")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")],
    ])
    await callback.message.answer(
        f"🌊 Оформление подписки TuVPN\n\n🔹 Устройств: {devices}\nВыберите период:",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "soon")
async def soon(callback: types.CallbackQuery):
    await callback.answer("⏳ Оплата появится совсем скоро! Пока пиши в помощь.", show_alert=True)

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
        "🎬 Контент → YouTube, Instagram без границ\n"
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
        "Твой друг получит 3 дня TuVPN бесплатно 🎁\n\n"
        "А ты получишь:\n"
        "➕ 3 дня — за каждую регистрацию\n"
        "➕ 7 дней — за каждую оплату друга\n\n"
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
        "💻 Windows / Mac:\n"
        "1. Скачай Hiddify или Nekoray\n"
        "2. Импортируй ссылку подписки\n\n"
        "🆘 Не выходит? Пиши — поможем!",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "support")
async def support(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])
    await callback.message.answer(
        "🛠 Помощь TuVPN\n\n"
        "На связи и готовы решить любой вопрос!\n\n"
        "✉️ Пиши — отвечаем быстро\n"
        "⏱ Среднее время ответа: до 1 часа\n\n"
        "Написать: @MaxArtVPN_bot",
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back")
async def back(callback: types.CallbackQuery):
    await callback.message.answer("Главное меню:", reply_markup=main_menu())
    await callback.answer()

async def main():
    logging.basicConfig(level=logging.INFO)
    init_db()
    asyncio.create_task(check_expired())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
