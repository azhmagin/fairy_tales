"""aiogram 3 handlers: the user funnel from /start to payment. Generation happens in the worker."""
from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardRemove,
)
from sqlalchemy import func, select

from storybook.analytics import track
from storybook.bot import texts
from storybook.config import get_settings
from storybook.content import STYLES, get_plot, load_plots
from storybook.db import session
from storybook.db.models import CharacterSheetRow, Child, Event, Order, Payment, User
from storybook.domain import ChildProfile, Gender, OrderStatus, PaymentStatus
from storybook.generation import illustration_generator
from storybook.orders import create_order, get_or_create_user, mark_paid, transition
from storybook.payments import get_provider, short_code
from storybook.storage import get_storage, strip_exif_and_resize
from storybook.worker.pipeline import make_sheet

log = structlog.get_logger()
router = Router()


class Flow(StatesGroup):
    consent = State()
    photos = State()
    name = State()
    age = State()
    gender = State()
    plot = State()
    preview = State()
    payment = State()


def _ikb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in r] for r in rows])


# ---------- start & consent ----------

@router.message(CommandStart())
async def start(m: Message, command: CommandObject, state: FSMContext) -> None:
    st = get_settings()
    ref = (command.args or "").strip() or None
    async with session() as s:
        user, created = await get_or_create_user(s, m.from_user.id, m.from_user.username, ref)
        consented = user.consent_at is not None
    await track("bot_start", user_id=m.from_user.id, ref=ref, new=created)
    await state.clear()
    await m.answer(texts.WELCOME.format(price=st.price_kzt), reply_markup=ReplyKeyboardRemove())
    if consented:
        await _ask_photos(m, state)
    else:
        await m.answer(
            texts.CONSENT.format(days=st.photo_retention_days, privacy_url="https://example.kz/privacy"),
            reply_markup=_ikb([[(texts.CONSENT_BTN, "consent:yes")]]),
        )
        await state.set_state(Flow.consent)


@router.callback_query(Flow.consent, F.data == "consent:yes")
async def consent(cq: CallbackQuery, state: FSMContext) -> None:
    async with session() as s:
        u = await s.get(User, cq.from_user.id)
        u.consent_at = datetime.now(UTC)
    await track("consent_given", user_id=cq.from_user.id)
    await cq.answer()
    await _ask_photos(cq.message, state)


async def _ask_photos(m: Message, state: FSMContext) -> None:
    await state.set_state(Flow.photos)
    await state.update_data(photos=[])
    await m.answer(texts.ASK_PHOTO, reply_markup=_ikb([[(texts.PHOTO_DONE_BTN, "photos:done")]]))


# ---------- photos ----------

@router.message(Flow.photos, F.photo)
async def photo(m: Message, state: FSMContext) -> None:
    data = await state.get_data()
    photos: list[str] = data.get("photos", [])
    if len(photos) >= 3:
        await m.answer(texts.PHOTO_LIMIT)
        return
    best = m.photo[-1]
    if min(best.width, best.height) < 512:
        await track("photo_rejected", user_id=m.from_user.id, reason="too_small")
        await m.answer(texts.PHOTO_TOO_SMALL)
        return
    buf = io.BytesIO()
    await m.bot.download(best, destination=buf)
    clean = strip_exif_and_resize(buf.getvalue())
    key = f"photos/{m.from_user.id}/{uuid.uuid4().hex}.jpg"
    await get_storage().put(key, clean, "image/jpeg")
    photos.append(key)
    await state.update_data(photos=photos)
    await track("photo_uploaded", user_id=m.from_user.id, n=len(photos))
    await m.answer(texts.PHOTO_OK.format(n=len(photos)), reply_markup=_ikb([[(texts.PHOTO_DONE_BTN, "photos:done")]]))


@router.message(Flow.photos, F.document | F.sticker)
async def not_photo(m: Message) -> None:
    await m.answer(texts.PHOTO_NOT_PHOTO)


@router.callback_query(Flow.photos, F.data == "photos:done")
async def photos_done(cq: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await cq.answer()
    if not data.get("photos"):
        await cq.message.answer(texts.ASK_PHOTO)
        return
    await state.set_state(Flow.name)
    await cq.message.answer(texts.ASK_NAME)


# ---------- child info ----------

@router.message(Flow.name, F.text)
async def name(m: Message, state: FSMContext) -> None:
    n = m.text.strip()
    if not (1 <= len(n) <= 30) or n.startswith("/"):
        await m.answer(texts.ASK_NAME)
        return
    await state.update_data(name=n)
    await state.set_state(Flow.age)
    await m.answer(texts.ASK_AGE.format(name=n))


@router.message(Flow.age, F.text)
async def age(m: Message, state: FSMContext) -> None:
    try:
        a = int(m.text.strip())
        assert 1 <= a <= 14
    except Exception:
        await m.answer(texts.BAD_AGE)
        return
    await state.update_data(age=a)
    d = await state.get_data()
    await state.set_state(Flow.gender)
    await m.answer(texts.ASK_GENDER.format(name=d["name"]), reply_markup=_ikb([[(texts.GENDER_BOY, "g:boy"), (texts.GENDER_GIRL, "g:girl")]]))


@router.callback_query(Flow.gender, F.data.startswith("g:"))
async def gender(cq: CallbackQuery, state: FSMContext) -> None:
    g = cq.data.split(":")[1]
    d = await state.get_data()
    async with session() as s:
        ch = Child(user_id=cq.from_user.id, name=d["name"], age=d["age"], gender=g, photo_keys=d["photos"])
        s.add(ch)
        await s.flush()
        child_id = str(ch.id)
    await state.update_data(gender=g, child_id=child_id)
    await track("child_info_filled", user_id=cq.from_user.id, age=d["age"], gender=g)
    await cq.answer()
    await state.set_state(Flow.plot)
    rows = [[(f"{p.emoji} {p.title.format(name=d['name'])}", f"plot:{p.code}")] for p in load_plots().values()]
    await cq.message.answer(texts.ASK_PLOT.format(name=d["name"]), reply_markup=_ikb(rows))


# ---------- plot & preview ----------

@router.callback_query(Flow.plot, F.data.startswith("plot:"))
async def plot_chosen(cq: CallbackQuery, state: FSMContext) -> None:
    code = cq.data.split(":")[1]
    plot = get_plot(code)
    d = await state.get_data()
    await cq.answer()
    await cq.message.answer(texts.PLOT_CHOSEN.format(emoji=plot.emoji, title=plot.title.format(name=d["name"]), teaser=plot.teaser.format(name=d["name"]), name=d["name"]))
    async with session() as s:
        child = await s.get(Child, uuid.UUID(d["child_id"]))
        order = await create_order(s, cq.from_user.id, child, code)
        order_id = order.id
    await state.update_data(order_id=str(order_id), plot=code)
    await track("plot_selected", user_id=cq.from_user.id, order_id=order_id, plot=code)
    await state.set_state(Flow.preview)
    await _make_preview(cq.message, state, cq.from_user.id)


async def _preview_count_today(s, user_id: int) -> int:
    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return (await s.execute(select(func.count()).select_from(Event).where(Event.user_id == user_id, Event.name == "preview_generated", Event.ts >= since))).scalar_one()


async def _make_preview(m: Message, state: FSMContext, user_id: int) -> None:
    st = get_settings()
    d = await state.get_data()
    order_id = uuid.UUID(d["order_id"])
    async with session() as s:
        if await _preview_count_today(s, user_id) >= st.preview_daily_limit:
            await m.answer(texts.PREVIEW_LIMIT, reply_markup=_ikb([[(texts.PREVIEW_PAY_BTN.format(price=st.price_kzt), "pay:start")]]))
            return
    child = ChildProfile(name=d["name"], age=d["age"], gender=Gender(d["gender"]), photo_keys=d["photos"])
    plot = get_plot(d["plot"])
    wait = await m.answer("🎨 Рисуем…")
    deps = _preview_deps()
    try:
        sheet, cost = await make_sheet(deps, order_id, child, plot, "soft3d")
    except Exception as e:
        log.exception("preview_failed")
        await wait.edit_text("Не получилось нарисовать с этими фото 😔 Попробуйте прислать другое фото: /start")
        return
    async with session() as s:
        row = CharacterSheetRow(child_id=uuid.UUID(d["child_id"]), style="soft3d", image_key=sheet.image_key, reference_photo_key=sheet.reference_photo_key, description=sheet.description, model=sheet.model)
        s.add(row)
        await s.flush()
        order = await s.get(Order, order_id)
        order.character_sheet_id = row.id
        order.preview_key = sheet.image_key
        if order.status == OrderStatus.DRAFT.value:
            await transition(s, order, OrderStatus.PREVIEW_READY)
        from storybook.db.models import Job
        s.add(Job(order_id=order_id, stage="preview", status="OK", cost_usd=cost, provider=st.image_provider, finished_at=datetime.now(UTC)))
    await track("preview_generated", user_id=user_id, order_id=order_id, cost_usd=cost)
    img = await get_storage().get(sheet.image_key)
    await wait.delete()
    await m.answer_photo(
        BufferedInputFile(img, filename="preview.png"),
        caption=texts.PREVIEW_CAPTION.format(name=d["name"], price=st.price_kzt),
        reply_markup=_ikb([[(texts.PREVIEW_PAY_BTN.format(price=st.price_kzt), "pay:start")], [(texts.PREVIEW_REDO_BTN, "preview:redo")]]),
    )


def _preview_deps():
    from storybook.generation import face_qa
    from storybook.worker.pipeline import PipelineDeps

    return PipelineDeps(storage=get_storage(), story_gen=None, image_gen=illustration_generator(), face_qa=face_qa())


@router.callback_query(Flow.preview, F.data == "preview:redo")
async def preview_redo(cq: CallbackQuery, state: FSMContext) -> None:
    await cq.answer()
    await _make_preview(cq.message, state, cq.from_user.id)


# ---------- payment ----------

@router.callback_query(F.data == "pay:start")
@router.message(Command("pay"))
async def pay_start(event: Message | CallbackQuery, state: FSMContext) -> None:
    m = event.message if isinstance(event, CallbackQuery) else event
    user_id = event.from_user.id
    if isinstance(event, CallbackQuery):
        await event.answer()
    d = await state.get_data()
    if not d.get("order_id"):
        await m.answer(texts.UNKNOWN)
        return
    order_id = uuid.UUID(d["order_id"])
    st = get_settings()
    provider = get_provider()
    async with session() as s:
        order = await s.get(Order, order_id)
        if order.status == OrderStatus.PREVIEW_READY.value:
            await transition(s, order, OrderStatus.AWAITING_PAYMENT)
        intent = await provider.create_payment(order)
        p = (await s.execute(select(Payment).where(Payment.order_id == order_id))).scalar_one_or_none()
        if p is None:
            s.add(Payment(order_id=order_id, provider=intent.provider, provider_ref=intent.provider_ref, amount=intent.amount, currency=intent.currency))
    await state.set_state(Flow.payment)
    await track("checkout_started", user_id=user_id, order_id=order_id, provider=provider.name)

    if provider.name == "stars":
        await m.answer_invoice(
            title=texts.PAY_STARS_TITLE.format(name=d["name"]), description=texts.PAY_STARS_DESC, payload=intent.invoice_payload,
            currency="XTR", prices=[LabeledPrice(label="Книга", amount=intent.amount)],
        )
    elif provider.name == "kaspi_link":
        code = short_code(order_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=texts.PAY_OPEN_BTN, url=intent.url)],
            [InlineKeyboardButton(text=texts.PAY_DONE_BTN, callback_data="pay:done")],
        ])
        await m.answer(texts.PAY_KASPI.format(price=st.price_kzt, code=code), reply_markup=kb, parse_mode="HTML")
    else:  # mock: auto-confirm for local dev
        async with session() as s:
            await mark_paid(s, order_id, provider.parse_callback({"order_id": str(order_id), "amount": st.price_kzt}))
        await _on_paid(m, state, user_id, order_id)


@router.callback_query(Flow.payment, F.data == "pay:done")
async def pay_done(cq: CallbackQuery, state: FSMContext) -> None:
    from storybook.bot.notify import notify_admin

    d = await state.get_data()
    await cq.answer()
    await cq.message.answer(texts.PAY_WAITING)
    await notify_admin(f"💳 Пользователь {cq.from_user.id} (@{cq.from_user.username}) сообщил об оплате.\nЗаказ {d['order_id']}, код {short_code(uuid.UUID(d['order_id']))}\nПодтвердить: /confirm {d['order_id']}")


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery) -> None:
    await q.answer(ok=True)


@router.message(F.successful_payment)
async def stars_paid(m: Message, state: FSMContext) -> None:
    from storybook.payments import StarsProvider

    ev = StarsProvider().parse_callback(m.successful_payment.model_dump())
    async with session() as s:
        order = await mark_paid(s, ev.order_id, ev)
    if order:
        await _on_paid(m, state, m.from_user.id, ev.order_id)


async def _on_paid(m: Message, state: FSMContext, user_id: int, order_id: uuid.UUID) -> None:
    d = await state.get_data()
    await track("payment_succeeded", user_id=user_id, order_id=order_id)
    await m.answer(texts.PAID.format(name=d.get("name", "")))
    prog = await m.answer(texts.PROGRESS_INIT)
    async with session() as s:
        order = await s.get(Order, order_id)
        order.progress_msg_id = prog.message_id
    await state.clear()


# ---------- misc ----------

@router.message(Command("cancel"))
async def cancel(m: Message, state: FSMContext) -> None:
    await state.clear()
    await m.answer(texts.CANCELLED, reply_markup=ReplyKeyboardRemove())


@router.message(Command("delete_my_data"))
async def delete_my_data(m: Message, state: FSMContext) -> None:
    storage = get_storage()
    async with session() as s:
        rows = (await s.execute(select(Child).where(Child.user_id == m.from_user.id))).scalars().all()
        for ch in rows:
            for k in ch.photo_keys:
                await storage.delete(k)
            ch.photo_keys = []
            ch.name = "—"
    await state.clear()
    await m.answer(texts.DELETED)


@router.message()
async def fallback(m: Message) -> None:
    await m.answer(texts.UNKNOWN)
