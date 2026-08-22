"""Admin commands: manual payment confirmation, review gallery, regeneration, funnel stats."""
from __future__ import annotations

import uuid
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from sqlalchemy import func, select

from storybook.analytics import track
from storybook.config import get_settings
from storybook.db import session
from storybook.db.models import Book, Event, Order, Page
from storybook.domain import OrderStatus, PaymentEvent, PaymentStatus
from storybook.orders import mark_paid, transition
from storybook.storage import get_storage

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in (get_settings().admin_ids or [])


router.message.filter(lambda m: _is_admin(m.from_user.id))
router.callback_query.filter(lambda c: _is_admin(c.from_user.id))


@router.message(Command("confirm"))
async def confirm(m: Message, command: CommandObject) -> None:
    """/confirm <order_id> — manual Kaspi confirmation (temporary, see tech-debt register)."""
    from storybook.bot import texts
    from storybook.bot.notify import send_text

    try:
        oid = uuid.UUID((command.args or "").strip())
    except ValueError:
        await m.answer("Использование: /confirm <order_id>")
        return
    async with session() as s:
        o = await s.get(Order, oid)
        if not o:
            await m.answer("Заказ не найден")
            return
        ev = PaymentEvent(provider="kaspi_link", provider_ref=f"kaspi:{oid.hex[:6].upper()}", status=PaymentStatus.SUCCEEDED, amount=o.price_kzt, raw={"manual": True, "by": m.from_user.id}, order_id=oid)
        order = await mark_paid(s, oid, ev, confirmed_by=m.from_user.id)
        user_id = o.user_id
    if order is None:
        await m.answer(f"Заказ {oid}: уже оплачен или не в статусе ожидания")
        return
    await track("payment_succeeded", user_id=user_id, order_id=oid, manual=True)
    await m.answer(f"✅ Заказ {oid} отмечен как оплаченный, генерация поставлена в очередь")
    await send_text(user_id, texts.PAID.format(name=""))
    prog = await m.bot.send_message(user_id, texts.PROGRESS_INIT)
    async with session() as s:
        o = await s.get(Order, oid)
        o.progress_msg_id = prog.message_id


@router.message(Command("review"))
async def review(m: Message, command: CommandObject) -> None:
    """/review <order_id> — show pages with face scores and approve/regenerate buttons."""
    try:
        oid = uuid.UUID((command.args or "").strip())
    except ValueError:
        await m.answer("Использование: /review <order_id>")
        return
    storage = get_storage()
    async with session() as s:
        book = (await s.execute(select(Book).where(Book.order_id == oid))).scalar_one_or_none()
        if not book:
            await m.answer("Книга ещё не создана")
            return
        pages = (await s.execute(select(Page).where(Page.book_id == book.id).order_by(Page.n))).scalars().all()
        items = [(p.n, p.image_key, p.face_score, p.attempts) for p in pages]
    media = []
    for n, key, score, att in items[:10]:
        img = await storage.get(key)
        media.append(InputMediaPhoto(media=BufferedInputFile(img, filename=f"{n}.png"), caption=f"стр. {n} · score={score if score is not None else '—'} · попыток {att}"))
    if media:
        await m.answer_media_group(media)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить родителю", callback_data=f"adm:deliver:{oid}")],
        [InlineKeyboardButton(text="🔁 Перегенерировать всё", callback_data=f"adm:regen:{oid}")],
    ])
    await m.answer(f"Заказ {oid}. Для перерисовки одной страницы: /regen_page {oid} <n>", reply_markup=kb)


@router.callback_query(F.data.startswith("adm:deliver:"))
async def adm_deliver(cq: CallbackQuery) -> None:
    from storybook.bot.notify import deliver_book

    oid = uuid.UUID(cq.data.split(":")[2])
    await cq.answer("Отправляю")
    await deliver_book(oid)
    await cq.message.answer(f"📨 Заказ {oid} отправлен")


@router.callback_query(F.data.startswith("adm:regen:"))
async def adm_regen(cq: CallbackQuery) -> None:
    oid = uuid.UUID(cq.data.split(":")[2])
    async with session() as s:
        o = await s.get(Order, oid)
        await transition(s, o, OrderStatus.GENERATING)
        o.enqueued_at = None
        o.status = OrderStatus.PAID.value  # back to outbox; cheap way to re-enqueue through the same guarantee
        o.regen_count += 1
    await cq.answer("В очереди")
    await cq.message.answer(f"🔁 Заказ {oid} поставлен на полную перегенерацию")


@router.message(Command("stats"))
async def stats(m: Message) -> None:
    """Funnel for the last 7 days, straight from Postgres."""
    async with session() as s:
        rows = (await s.execute(
            select(Event.name, func.count(func.distinct(Event.user_id)))
            .where(Event.ts >= func.now() - timedelta(days=7))
            .group_by(Event.name)
        )).all()
    counts = dict(rows)
    order = ["bot_start", "consent_given", "photo_uploaded", "child_info_filled", "plot_selected", "preview_generated", "checkout_started", "payment_succeeded", "book_delivered"]
    lines = ["Воронка за 7 дней (уникальные пользователи):"]
    base = counts.get("bot_start", 0) or 1
    for k in order:
        v = counts.get(k, 0)
        lines.append(f"{k:<20} {v:>5}  ({100 * v / base:.1f}%)")
    await m.answer("<pre>" + "\n".join(lines) + "</pre>", parse_mode="HTML")
