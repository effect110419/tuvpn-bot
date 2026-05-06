"""
TuVPN Support Bot — @TuVPNSupport_bot
Тикет-система с FAQ и уведомлениями админам.
"""

import asyncio
import logging
import html
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from supabase import create_client, Client

from config import SUPPORT_BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY, MAIN_BOT_USERNAME, FALLBACK_ADMIN_IDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("support_bot")

bot = Bot(
    token=SUPPORT_BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================================
# FAQ — готовые ответы
# ============================================================
FAQ = {
    "faq_install_iphone": {
        "title": "📱 Как установить на iPhone",
        "answer": (
            "<b>Установка на iPhone:</b>\n\n"
            "1. Установите приложение <b>Happ Plus</b> из App Store\n"
            "2. Откройте бот @MaxArtVPN_bot и нажмите «Моя подписка»\n"
            "3. Скопируйте ссылку подписки\n"
            "4. В Happ Plus нажмите «+» → «Добавить из буфера обмена»\n"
            "5. Включите VPN кнопкой подключения\n\n"
            "Если не получается — нажмите «Написать в поддержку»."
        ),
    },
    "faq_install_android": {
        "title": "🤖 Как установить на Android",
        "answer": (
            "<b>Установка на Android:</b>\n\n"
            "1. Установите <b>v2rayTun</b> из Play Market\n"
            "2. Откройте @MaxArtVPN_bot → «Моя подписка»\n"
            "3. Скопируйте ссылку подписки\n"
            "4. В v2rayTun нажмите «+» → «Импорт из буфера»\n"
            "5. Включите VPN\n\n"
            "Если возникли сложности — напишите нам."
        ),
    },
    "faq_not_working": {
        "title": "⚠️ VPN не подключается",
        "answer": (
            "<b>Если VPN не работает:</b>\n\n"
            "• Проверьте что подписка активна в @MaxArtVPN_bot\n"
            "• Полностью выключите VPN и включите снова\n"
            "• Перезапустите приложение\n"
            "• Попробуйте переподключиться через 1-2 минуты\n"
            "• Убедитесь что есть доступ в интернет без VPN\n\n"
            "Если ничего не помогло — напишите в поддержку, "
            "укажите модель устройства и приложение."
        ),
    },
    "faq_payment": {
        "title": "💳 Вопросы по оплате",
        "answer": (
            "<b>Оплата подписки:</b>\n\n"
            "• Оплата через ЮКассу (карты МИР, Visa, Mastercard)\n"
            "• После оплаты ключ выдаётся автоматически в @MaxArtVPN_bot\n"
            "• Если деньги списались, но ключ не пришёл — напишите нам, "
            "укажите время оплаты и сумму\n\n"
            "Все тарифы доступны в основном боте."
        ),
    },
    "faq_devices": {
        "title": "📲 Несколько устройств",
        "answer": (
            "<b>Подключение нескольких устройств:</b>\n\n"
            "Количество устройств зависит от вашего тарифа (1, 2 или 5).\n"
            "Используйте <b>одну и ту же ссылку подписки</b> на всех устройствах.\n\n"
            "Если превышен лимит — старое устройство будет отключено."
        ),
    },
    "faq_change_country": {
        "title": "🌍 Смена страны / сервера",
        "answer": (
            "<b>Сейчас доступен один сервер — Финляндия 🇫🇮</b>\n\n"
            "Мы работаем над добавлением серверов в других странах. "
            "Следите за новостями в боте."
        ),
    },
}

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ Частые вопросы (FAQ)", callback_data="show_faq")],
        [InlineKeyboardButton(text="✍️ Написать в поддержку", callback_data="new_ticket")],
        [InlineKeyboardButton(text="📋 Мои обращения", callback_data="my_tickets")],
        [InlineKeyboardButton(text="🤖 Основной бот", url=f"https://t.me/{MAIN_BOT_USERNAME}")],
    ])


def faq_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=item["title"], callback_data=key)]
        for key, item in FAQ.items()
    ]
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_answer_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❓ Другой вопрос", callback_data="show_faq")],
        [InlineKeyboardButton(text="✍️ Написать в поддержку", callback_data="new_ticket")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_menu")],
    ])


def cancel_ticket_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="back_to_menu")],
    ])


def admin_ticket_kb(ticket_id: int, status: str) -> InlineKeyboardMarkup:
    rows = []
    if status == "open":
        rows.append([InlineKeyboardButton(text="📥 Взять в работу", callback_data=f"adm_take_{ticket_id}")])
    if status in ("open", "in_progress"):
        rows.append([InlineKeyboardButton(text="✅ Закрыть", callback_data=f"adm_close_{ticket_id}")])
    rows.append([InlineKeyboardButton(text="💬 Ответить", callback_data=f"adm_reply_{ticket_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ============================================================
# СОСТОЯНИЯ FSM
# ============================================================
class UserStates(StatesGroup):
    writing_ticket = State()
    chatting = State()


class AdminStates(StatesGroup):
    replying = State()


# ============================================================
# РАБОТА С БД
# ============================================================
async def get_admins(active_only: bool = True, role_filter: Optional[str] = None) -> list:
    try:
        q = sb.table("support_admins").select("*")
        if active_only:
            q = q.eq("is_active", True)
        if role_filter:
            q = q.eq("role", role_filter)
        res = q.execute()
        return res.data or []
    except Exception as e:
        log.error(f"Не удалось получить админов из БД: {e}")
        return [{"user_id": uid, "role": "admin", "is_active": True} for uid in FALLBACK_ADMIN_IDS]


async def is_admin(user_id: int) -> bool:
    admins = await get_admins(active_only=True)
    return any(a["user_id"] == user_id and a.get("role") == "admin" for a in admins)


async def get_open_ticket_for_user(user_id: int) -> Optional[dict]:
    res = (
        sb.table("support_tickets")
        .select("*")
        .eq("user_id", user_id)
        .in_("status", ["open", "in_progress"])
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def create_ticket(user: dict, first_message: str) -> dict:
    subject = (first_message or "")[:100]
    payload = {
        "user_id": user["id"],
        "username": user.get("username"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "subject": subject,
        "status": "open",
    }
    res = sb.table("support_tickets").insert(payload).execute()
    return res.data[0]


async def add_message(ticket_id, sender_type, sender_id, sender_name, text, tg_message_id=None):
    sb.table("support_messages").insert({
        "ticket_id": ticket_id,
        "sender_type": sender_type,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "message_text": text,
        "telegram_message_id": tg_message_id,
    }).execute()


async def update_ticket_status(ticket_id: int, status: str, admin_id: Optional[int] = None):
    payload = {"status": status}
    if status == "in_progress" and admin_id is not None:
        payload["assigned_admin_id"] = admin_id
    if status == "closed":
        payload["closed_at"] = datetime.now(timezone.utc).isoformat()
    sb.table("support_tickets").update(payload).eq("id", ticket_id).execute()


async def get_ticket(ticket_id: int) -> Optional[dict]:
    res = sb.table("support_tickets").select("*").eq("id", ticket_id).limit(1).execute()
    return res.data[0] if res.data else None


async def get_user_tickets(user_id: int, limit: int = 10) -> list:
    res = (
        sb.table("support_tickets")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


# ============================================================
# УВЕДОМЛЕНИЯ АДМИНАМ
# ============================================================
async def notify_admins(text: str, ticket_id: Optional[int] = None, ticket_status: str = "open"):
    admins = await get_admins(active_only=True)
    kb = admin_ticket_kb(ticket_id, ticket_status) if ticket_id else None
    for admin in admins:
        try:
            await bot.send_message(chat_id=admin["user_id"], text=text, reply_markup=kb)
        except Exception as e:
            log.warning(f"Не отправилось админу {admin['user_id']}: {e}")


def format_user_info(user: dict) -> str:
    parts = []
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))
    if name:
        parts.append(f"<b>{html.escape(name)}</b>")
    if user.get("username"):
        parts.append(f"@{user['username']}")
    parts.append(f"<code>{user['id']}</code>")
    return " · ".join(parts)


# ============================================================
# /start
# ============================================================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    if await is_admin(message.from_user.id):
        await message.answer(
            "👋 Привет, админ!\n\n"
            "Доступные команды:\n"
            "/tickets — список открытых тикетов\n"
            "/ticket &lt;id&gt; — посмотреть тикет\n"
            "/take &lt;id&gt; — взять в работу\n"
            "/close &lt;id&gt; — закрыть тикет\n"
            "/reply &lt;id&gt; &lt;текст&gt; — ответить\n\n"
            "Также можно отвечать через кнопку «Ответить» под уведомлением."
        )
        return

    await message.answer(
        "👋 <b>Привет! Это служба поддержки TuVPN.</b>\n\n"
        "Здесь вы можете:\n"
        "• Найти ответ в FAQ\n"
        "• Написать нам, если что-то не работает\n"
        "• Посмотреть статус ваших обращений\n\n"
        "Чем можем помочь?",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Главное меню. Чем можем помочь?", reply_markup=main_menu_kb())
    await call.answer()


# ============================================================
# FAQ
# ============================================================
@router.callback_query(F.data == "show_faq")
async def cb_show_faq(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❓ <b>Частые вопросы</b>\n\nВыберите тему:", reply_markup=faq_kb())
    await call.answer()


@router.callback_query(F.data.startswith("faq_"))
async def cb_faq_answer(call: CallbackQuery):
    item = FAQ.get(call.data)
    if not item:
        await call.answer("Раздел не найден", show_alert=True)
        return
    await call.message.edit_text(item["answer"], reply_markup=faq_answer_kb())
    await call.answer()


# ============================================================
# СОЗДАНИЕ ТИКЕТА (пользователь)
# ============================================================
@router.callback_query(F.data == "new_ticket")
async def cb_new_ticket(call: CallbackQuery, state: FSMContext):
    existing = await get_open_ticket_for_user(call.from_user.id)
    if existing:
        await state.set_state(UserStates.chatting)
        await state.update_data(ticket_id=existing["id"])
        await call.message.edit_text(
            f"📨 У вас уже есть активное обращение #{existing['id']}.\n"
            f"Просто напишите сообщение — оно попадёт в поддержку.\n\n"
            f"Чтобы вернуться в меню — /start",
        )
        await call.answer()
        return

    await state.set_state(UserStates.writing_ticket)
    await call.message.edit_text(
        "✍️ <b>Опишите вашу проблему</b>\n\n"
        "Напишите одним сообщением — что случилось, какое устройство, "
        "какое приложение используете. Чем подробнее, тем быстрее поможем.\n\n"
        "Можно отправить скриншот.",
        reply_markup=cancel_ticket_kb(),
    )
    await call.answer()


@router.message(UserStates.writing_ticket)
async def first_ticket_message(message: Message, state: FSMContext):
    user = {
        "id": message.from_user.id,
        "username": message.from_user.username,
        "first_name": message.from_user.first_name,
        "last_name": message.from_user.last_name,
    }
    text = message.text or message.caption or "(без текста / медиа)"

    ticket = await create_ticket(user, text)
    ticket_id = ticket["id"]

    await add_message(
        ticket_id=ticket_id,
        sender_type="user",
        sender_id=user["id"],
        sender_name=user.get("first_name") or user.get("username") or str(user["id"]),
        text=text,
        tg_message_id=message.message_id,
    )

    await state.set_state(UserStates.chatting)
    await state.update_data(ticket_id=ticket_id)

    await message.answer(
        f"✅ Обращение <b>#{ticket_id}</b> создано.\n\n"
        f"Мы получили ваше сообщение и скоро ответим. "
        f"Можете продолжать писать сюда — все сообщения попадут в это же обращение.\n\n"
        f"Команда /start — главное меню."
    )

    user_info = format_user_info(user)
    notification = (
        f"🆕 <b>Новый тикет #{ticket_id}</b>\n\n"
        f"От: {user_info}\n\n"
        f"<i>Сообщение:</i>\n{html.escape(text)}"
    )
    await notify_admins(notification, ticket_id=ticket_id, ticket_status="open")

    if message.photo or message.document or message.video or message.voice:
        admins = await get_admins(active_only=True)
        for admin in admins:
            try:
                await message.forward(admin["user_id"])
            except Exception as e:
                log.warning(f"Форвард медиа не удался для {admin['user_id']}: {e}")


@router.message(UserStates.chatting)
async def continue_ticket_message(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get("ticket_id")

    if not ticket_id:
        ticket = await get_open_ticket_for_user(message.from_user.id)
        if ticket:
            ticket_id = ticket["id"]
            await state.update_data(ticket_id=ticket_id)
        else:
            await state.clear()
            await message.answer("Активного обращения нет. Откройте новое через /start.")
            return

    text = message.text or message.caption or "(без текста / медиа)"
    user = message.from_user

    await add_message(
        ticket_id=ticket_id,
        sender_type="user",
        sender_id=user.id,
        sender_name=user.first_name or user.username or str(user.id),
        text=text,
        tg_message_id=message.message_id,
    )

    ticket = await get_ticket(ticket_id)
    if ticket and ticket["status"] == "closed":
        await update_ticket_status(ticket_id, "open")

    user_info = format_user_info({
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
    })

    forward_text = (
        f"💬 <b>Тикет #{ticket_id}</b> — новое сообщение\n"
        f"От: {user_info}\n\n"
        f"{html.escape(text)}"
    )
    await notify_admins(forward_text, ticket_id=ticket_id, ticket_status=ticket["status"] if ticket else "open")

    if message.photo or message.document or message.video or message.voice:
        admins = await get_admins(active_only=True)
        for admin in admins:
            try:
                await message.forward(admin["user_id"])
            except Exception:
                pass

    await message.answer("✉️ Передано в поддержку.")


# ============================================================
# МОИ ОБРАЩЕНИЯ
# ============================================================
@router.callback_query(F.data == "my_tickets")
async def cb_my_tickets(call: CallbackQuery, state: FSMContext):
    await state.clear()
    tickets = await get_user_tickets(call.from_user.id)

    if not tickets:
        await call.message.edit_text("У вас пока нет обращений.", reply_markup=main_menu_kb())
        await call.answer()
        return

    status_ru = {"open": "🟢 Открыт", "in_progress": "🟡 В работе", "closed": "✅ Закрыт"}
    lines = ["📋 <b>Ваши обращения:</b>\n"]
    for t in tickets:
        created = t["created_at"][:10]
        status = status_ru.get(t["status"], t["status"])
        subj = (t.get("subject") or "—")[:60]
        lines.append(f"#{t['id']} · {status} · {created}\n<i>{html.escape(subj)}</i>\n")

    await call.message.edit_text("\n".join(lines), reply_markup=main_menu_kb())
    await call.answer()


# ============================================================
# АДМИНСКИЕ КОМАНДЫ
# ============================================================
@router.message(Command("tickets"))
async def cmd_tickets(message: Message):
    if not await is_admin(message.from_user.id):
        return

    res = (
        sb.table("support_tickets")
        .select("*")
        .in_("status", ["open", "in_progress"])
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    tickets = res.data or []

    if not tickets:
        await message.answer("✨ Открытых тикетов нет.")
        return

    status_emoji = {"open": "🟢", "in_progress": "🟡"}
    lines = [f"<b>Открытые тикеты ({len(tickets)}):</b>\n"]
    for t in tickets:
        emoji = status_emoji.get(t["status"], "•")
        name = t.get("first_name") or t.get("username") or str(t["user_id"])
        subj = (t.get("subject") or "—")[:50]
        lines.append(f"{emoji} #{t['id']} · {html.escape(name)} · <i>{html.escape(subj)}</i>")

    lines.append("\nКоманды: /ticket &lt;id&gt;, /take &lt;id&gt;, /close &lt;id&gt;, /reply &lt;id&gt; &lt;текст&gt;")
    await message.answer("\n".join(lines))


@router.message(Command("ticket"))
async def cmd_ticket_info(message: Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Используйте: /ticket &lt;id&gt;")
        return

    ticket_id = int(command.args.strip())
    ticket = await get_ticket(ticket_id)
    if not ticket:
        await message.answer(f"Тикет #{ticket_id} не найден.")
        return

    msgs_res = (
        sb.table("support_messages")
        .select("*")
        .eq("ticket_id", ticket_id)
        .order("created_at")
        .execute()
    )
    msgs = msgs_res.data or []

    user_info = format_user_info({
        "id": ticket["user_id"],
        "username": ticket.get("username"),
        "first_name": ticket.get("first_name"),
        "last_name": ticket.get("last_name"),
    })

    status_ru = {"open": "🟢 Открыт", "in_progress": "🟡 В работе", "closed": "✅ Закрыт"}
    header = (
        f"<b>Тикет #{ticket_id}</b>\n"
        f"Статус: {status_ru.get(ticket['status'], ticket['status'])}\n"
        f"Создан: {ticket['created_at'][:16]}\n"
        f"Пользователь: {user_info}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    body = []
    for m in msgs[-15:]:
        prefix = {"user": "👤", "admin": "🛠", "system": "ℹ️"}.get(m["sender_type"], "•")
        sender = m.get("sender_name") or "—"
        text = (m.get("message_text") or "")[:500]
        body.append(f"{prefix} <b>{html.escape(sender)}</b>: {html.escape(text)}")

    full = header + "\n\n" + "\n\n".join(body) if body else header + "\n\n<i>(сообщений нет)</i>"
    await message.answer(full[:4000], reply_markup=admin_ticket_kb(ticket_id, ticket["status"]))


@router.message(Command("take"))
async def cmd_take(message: Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Используйте: /take &lt;id&gt;")
        return

    ticket_id = int(command.args.strip())
    ticket = await get_ticket(ticket_id)
    if not ticket:
        await message.answer(f"Тикет #{ticket_id} не найден.")
        return

    await update_ticket_status(ticket_id, "in_progress", admin_id=message.from_user.id)
    await add_message(
        ticket_id=ticket_id,
        sender_type="system",
        sender_id=message.from_user.id,
        sender_name=message.from_user.first_name or "admin",
        text=f"Тикет взят в работу: {message.from_user.first_name}",
    )
    await message.answer(f"📥 Тикет #{ticket_id} в работе.")

    try:
        await bot.send_message(
            ticket["user_id"],
            f"🟡 Ваше обращение #{ticket_id} взято в работу. Скоро ответим.",
        )
    except Exception as e:
        log.warning(f"Не уведомили юзера {ticket['user_id']}: {e}")


@router.message(Command("close"))
async def cmd_close(message: Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        return
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Используйте: /close &lt;id&gt;")
        return

    ticket_id = int(command.args.strip())
    ticket = await get_ticket(ticket_id)
    if not ticket:
        await message.answer(f"Тикет #{ticket_id} не найден.")
        return

    await update_ticket_status(ticket_id, "closed")
    await add_message(
        ticket_id=ticket_id,
        sender_type="system",
        sender_id=message.from_user.id,
        sender_name=message.from_user.first_name or "admin",
        text="Тикет закрыт",
    )
    await message.answer(f"✅ Тикет #{ticket_id} закрыт.")

    try:
        await bot.send_message(
            ticket["user_id"],
            f"✅ Ваше обращение #{ticket_id} закрыто.\n"
            f"Если проблема осталась — напишите ещё раз, тикет переоткроется.",
        )
    except Exception as e:
        log.warning(f"Не уведомили юзера {ticket['user_id']}: {e}")


@router.message(Command("reply"))
async def cmd_reply(message: Message, command: CommandObject):
    if not await is_admin(message.from_user.id):
        return
    if not command.args:
        await message.answer("Используйте: /reply &lt;id&gt; &lt;текст&gt;")
        return

    parts = command.args.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await message.answer("Используйте: /reply &lt;id&gt; &lt;текст&gt;")
        return

    ticket_id = int(parts[0])
    reply_text = parts[1]
    await _send_reply(message, ticket_id, reply_text)


async def _send_reply(admin_message: Message, ticket_id: int, text: str):
    ticket = await get_ticket(ticket_id)
    if not ticket:
        await admin_message.answer(f"Тикет #{ticket_id} не найден.")
        return

    if ticket["status"] == "open":
        await update_ticket_status(ticket_id, "in_progress", admin_id=admin_message.from_user.id)

    await add_message(
        ticket_id=ticket_id,
        sender_type="admin",
        sender_id=admin_message.from_user.id,
        sender_name=admin_message.from_user.first_name or "support",
        text=text,
        tg_message_id=admin_message.message_id,
    )

    try:
        await bot.send_message(
            ticket["user_id"],
            f"🛠 <b>Поддержка TuVPN:</b>\n\n{html.escape(text)}",
        )
        await admin_message.answer(f"✉️ Отправлено в тикет #{ticket_id}.")
    except Exception as e:
        await admin_message.answer(f"⚠️ Не удалось отправить пользователю: {e}")


# ============================================================
# КНОПКИ ПОД АДМИНСКИМИ УВЕДОМЛЕНИЯМИ
# ============================================================
@router.callback_query(F.data.startswith("adm_take_"))
async def cb_adm_take(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        await call.answer("Только для админов", show_alert=True)
        return
    ticket_id = int(call.data.split("_")[-1])
    ticket = await get_ticket(ticket_id)
    if not ticket:
        await call.answer("Тикет не найден", show_alert=True)
        return

    await update_ticket_status(ticket_id, "in_progress", admin_id=call.from_user.id)
    await add_message(
        ticket_id=ticket_id,
        sender_type="system",
        sender_id=call.from_user.id,
        sender_name=call.from_user.first_name or "admin",
        text=f"Тикет взят в работу: {call.from_user.first_name}",
    )
    await call.answer(f"Тикет #{ticket_id} в работе")
    try:
        await call.message.edit_reply_markup(reply_markup=admin_ticket_kb(ticket_id, "in_progress"))
    except Exception:
        pass

    try:
        await bot.send_message(
            ticket["user_id"],
            f"🟡 Ваше обращение #{ticket_id} взято в работу. Скоро ответим.",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("adm_close_"))
async def cb_adm_close(call: CallbackQuery):
    if not await is_admin(call.from_user.id):
        await call.answer("Только для админов", show_alert=True)
        return
    ticket_id = int(call.data.split("_")[-1])
    ticket = await get_ticket(ticket_id)
    if not ticket:
        await call.answer("Тикет не найден", show_alert=True)
        return

    await update_ticket_status(ticket_id, "closed")
    await add_message(
        ticket_id=ticket_id,
        sender_type="system",
        sender_id=call.from_user.id,
        sender_name=call.from_user.first_name or "admin",
        text="Тикет закрыт",
    )
    await call.answer(f"Тикет #{ticket_id} закрыт")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    try:
        await bot.send_message(
            ticket["user_id"],
            f"✅ Ваше обращение #{ticket_id} закрыто.\n"
            f"Если проблема осталась — напишите ещё раз.",
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("adm_reply_"))
async def cb_adm_reply(call: CallbackQuery, state: FSMContext):
    if not await is_admin(call.from_user.id):
        await call.answer("Только для админов", show_alert=True)
        return
    ticket_id = int(call.data.split("_")[-1])
    await state.set_state(AdminStates.replying)
    await state.update_data(reply_ticket_id=ticket_id)
    await call.message.answer(
        f"✍️ Напишите ответ для тикета #{ticket_id} следующим сообщением.\n"
        f"Чтобы отменить — /cancel"
    )
    await call.answer()


@router.message(Command("cancel"), AdminStates.replying)
async def cancel_admin_reply(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")


@router.message(AdminStates.replying)
async def admin_reply_handler(message: Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    await state.clear()

    if not ticket_id:
        await message.answer("Не нашёл к какому тикету отвечать. Попробуйте ещё раз.")
        return

    text = message.text or message.caption or ""
    if not text:
        await message.answer("Пустое сообщение. Отмена.")
        return

    await _send_reply(message, ticket_id, text)


# ============================================================
# ЗАПУСК
# ============================================================
async def main():
    log.info("Support bot starting...")
    me = await bot.get_me()
    log.info(f"Bot: @{me.username} (id={me.id})")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
