"""Outbound messaging used by worker/scheduler (progress edits, admin alerts, PDF delivery)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from storybook.analytics import track
from storybook.bot import texts
from storybook.config import get_settings
from storybook.db import session
from storybook.db.models import Book, Child, Order, User
from storybook.domain import OrderStatus
from storybook.orders import transition
from storybook.storage import get_storage

log = structlog.get_logger()
_bot: Bot | None = None


def bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=get_settings().bot_token)
    return _bot


async def send_text(chat_id: int, text: str) -> None:
    try:
        await bot().send_message(chat_id, text)
    except Exception as e:
        log.warning("send_failed", chat_id=chat_id, error=str(e))


async def notify_admin(text: str) -> None:
    st = get_settings()
    if st.admin_chat_id:
        await send_text(st.admin_chat_id, text)


def progress_editor(chat_id: int, message_id: int | None):
    last = {"text": ""}

    async def _edit(text: str) -> None:
        if text == last["text"]:
            return
        last["text"] = text
        try:
            if message_id:
                await bot().edit_message_text(text, chat_id=chat_id, message_id=message_id)
            else:
                await bot().send_message(chat_id, text)
        except Exception as e:  # "message is not modified" etc. must not break the pipeline
            log.debug("progress_edit_failed", error=str(e))

    return _edit


async def deliver_book(order_id: uuid.UUID) -> None:
    """Send the PDF. Idempotent-ish: if already delivered, still resends (admin may call it on purpose)."""
    async with session() as s:
        order = await s.get(Order, order_id)
        book = (await s.execute(select(Book).where(Book.order_id == order_id))).scalar_one()
        child = await s.get(Child, order.child_id)
        user = await s.get(User, order.user_id)
        if order.status != OrderStatus.DELIVERED.value:
            await transition(s, order, OrderStatus.DELIVERED)
            order.delivered_at = datetime.now(UTC)
        pdf_key, title, name, chat_id, ref = book.pdf_key, book.title, child.name, order.user_id, user.ref_code
        child.photos_delete_at = datetime.now(UTC).replace(microsecond=0) + __import__("datetime").timedelta(days=get_settings().photo_retention_days)
    pdf = await get_storage().get(pdf_key)
    me = await bot().get_me()
    ref_link = f"https://t.me/{me.username}?start=ref_{ref}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=texts.DELIVERED_SHARE_BTN, switch_inline_query=f"Смотри, какую сказку сделали про моего ребёнка! {ref_link}"),
    ]])
    fname = f"{title}.pdf".replace("/", "-")
    await bot().send_document(chat_id, BufferedInputFile(pdf, filename=fname), caption=texts.DELIVERED.format(name=name, ref_link=ref_link), reply_markup=kb)
    await track("book_delivered", user_id=chat_id, order_id=order_id)
