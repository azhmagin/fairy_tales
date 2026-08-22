"""arq worker: DB-aware wrapper around the pure pipeline + scheduler jobs (outbox, payment reminders, cleanup)."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from storybook.analytics import track
from storybook.config import get_settings
from storybook.content import get_plot
from storybook.db import session
from storybook.db.models import Book, CharacterSheetRow, Child, Job, Order, Page, User
from storybook.domain import CharacterSheet, ChildProfile, Gender, OrderStatus
from storybook.generation import face_qa, illustration_generator, story_generator
from storybook.generation.budget import BudgetExceeded, ensure_budget
from storybook.orders import claim_unenqueued, mark_enqueued, transition
from storybook.storage import get_storage
from storybook.worker.pipeline import PipelineDeps, run_pipeline

log = structlog.get_logger()


def _deps() -> PipelineDeps:
    st = get_settings()
    return PipelineDeps(
        storage=get_storage(), story_gen=story_generator(), image_gen=illustration_generator(), face_qa=face_qa(),
        face_threshold=st.face_threshold, page_max_attempts=st.page_max_attempts, concurrency=st.image_concurrency,
    )


async def _job(order_id: uuid.UUID, stage: str, status: str, cost: float = 0.0, error: str | None = None, provider: str | None = None) -> None:
    async with session() as s:
        s.add(Job(order_id=order_id, stage=stage, status=status, cost_usd=cost, error=error, provider=provider, finished_at=datetime.now(UTC)))


async def generate_book(ctx, order_id_str: str) -> str:
    """Main task. Safe to re-run: skips if the order is not in a generatable state."""
    from storybook.bot.notify import progress_editor, notify_admin, deliver_book

    order_id = uuid.UUID(order_id_str)
    async with session() as s:
        order = await s.get(Order, order_id)
        if order is None or order.status not in (OrderStatus.PAID.value, OrderStatus.GENERATING.value):
            log.info("generate_skip", order_id=order_id_str, status=getattr(order, "status", None))
            return "skipped"
        try:
            await ensure_budget(s)
        except BudgetExceeded as e:
            await notify_admin(f"⛔ {e}\nЗаказ {order_id} отложен.")
            raise  # arq will retry later with backoff
        await transition(s, order, OrderStatus.GENERATING)
        child_row = await s.get(Child, order.child_id)
        sheet_row = await s.get(CharacterSheetRow, order.character_sheet_id)
        user = await s.get(User, order.user_id)
        plot = get_plot(order.plot_code)
        style = order.style
        preview_key = order.preview_key
        progress_msg_id = order.progress_msg_id
        chat_id = order.user_id
        lang = user.lang if user else "ru"

    child = ChildProfile(name=child_row.name, age=child_row.age, gender=Gender(child_row.gender), photo_keys=list(child_row.photo_keys))
    sheet = CharacterSheet(image_key=sheet_row.image_key, reference_photo_key=sheet_row.reference_photo_key, description=sheet_row.description, model=sheet_row.model)
    progress = progress_editor(chat_id, progress_msg_id)
    started = datetime.now(UTC)
    try:
        result = await run_pipeline(_deps(), order_id, child, plot, style, sheet, progress, lang, preview_cover_key=preview_key)
    except Exception as e:
        log.exception("pipeline_failed", order_id=order_id_str)
        await _job(order_id, "pipeline", "FAILED", error=str(e)[:2000])
        async with session() as s:
            order = await s.get(Order, order_id)
            await transition(s, order, OrderStatus.MANUAL_REVIEW)
        await notify_admin(f"🔴 Пайплайн упал, заказ {order_id}: {e}")
        await progress("😔 Что-то пошло не так. Мы уже разбираемся и пришлём книгу вручную — это займёт немного больше времени.")
        raise

    await _job(order_id, "pipeline", "OK", cost=result.cost_usd, provider=get_settings().image_provider)
    secs = (datetime.now(UTC) - started).total_seconds()
    async with session() as s:
        order = await s.get(Order, order_id)
        book = (await s.execute(select(Book).where(Book.order_id == order_id))).scalar_one_or_none()
        if book is None:
            book = Book(order_id=order_id)
            s.add(book)
            await s.flush()
        book.title = result.story.title
        book.story = {"title": result.story.title, "dedication": result.story.dedication, "moral": result.story.moral,
                      "pages": [{"n": p.n, "text": p.text, "scene_prompt": p.scene} for p in result.story.pages]}
        book.pdf_key = result.pdf_key
        for existing in (await s.execute(select(Page).where(Page.book_id == book.id))).scalars():
            await s.delete(existing)
        for sp, pr in zip(result.story.pages, result.pages, strict=True):
            s.add(Page(book_id=book.id, n=sp.n, text=sp.text, scene_prompt=sp.scene, image_key=pr.image_key, face_score=pr.face_score, attempts=pr.attempts))
        await transition(s, order, OrderStatus.QA)
        needs_review = get_settings().human_review or bool(result.low_score_pages)
        await transition(s, order, OrderStatus.REVIEW if needs_review else OrderStatus.DELIVERED)
        if not needs_review:
            order.delivered_at = datetime.now(UTC)
    await track("generation_finished", user_id=chat_id, order_id=order_id, seconds=round(secs), cost_usd=round(result.cost_usd, 3), low_pages=result.low_score_pages)

    if needs_review:
        await progress("✅ Книга готова и проходит финальную проверку. Пришлём через несколько минут!")
        await notify_admin(f"📘 Заказ {order_id} готов к проверке. Страницы с низким сходством: {result.low_score_pages or 'нет'}.\n/review {order_id}")
    else:
        await deliver_book(order_id)
    return "ok"


async def outbox_tick(ctx) -> int:
    """Every 10s: enqueue PAID orders that have no job yet. Guarantees no paid order is lost."""
    async with session() as s:
        ids = await claim_unenqueued(s)
        for oid in ids:
            await ctx["redis"].enqueue_job("generate_book", str(oid), _job_id=f"gen:{oid}")
        await mark_enqueued(s, ids)
    return len(ids)


async def payment_reminders(ctx) -> int:
    from storybook.bot.notify import send_text

    st = get_settings()
    n = 0
    async with session() as s:
        cutoff = datetime.now(UTC) - timedelta(minutes=st.payment_timeout_minutes)
        rows = (await s.execute(select(Order).where(Order.status == OrderStatus.AWAITING_PAYMENT.value, Order.updated_at < cutoff))).scalars().all()
        for o in rows:
            if o.regen_count == 0:  # reuse counter as "reminder sent" for this status; cheap and enough for MVP
                await send_text(o.user_id, f"Книга для вашего ребёнка почти готова к созданию ✨\nОсталось оплатить {o.price_kzt} ₸ — нажмите /pay")
                o.regen_count = 1
                n += 1
    return n


async def cleanup_photos(ctx) -> int:
    """Delete original photos after retention period (privacy by design)."""
    storage = get_storage()
    n = 0
    async with session() as s:
        rows = (await s.execute(select(Child).where(Child.photos_delete_at.is_not(None), Child.photos_delete_at < datetime.now(UTC)))).scalars().all()
        for ch in rows:
            for k in ch.photo_keys:
                await storage.delete(k)
                n += 1
            ch.photo_keys = []
            ch.photos_delete_at = None
    return n


async def startup(ctx) -> None:
    log.info("worker_started")


class WorkerSettings:
    functions = [generate_book]
    cron_jobs = [
        cron(outbox_tick, second={0, 10, 20, 30, 40, 50}),
        cron(payment_reminders, minute={0, 15, 30, 45}),
        cron(cleanup_photos, hour={3}, minute={0}),
    ]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 5
    job_timeout = 900  # 15 min per book
    max_tries = 3
    retry_jobs = True
