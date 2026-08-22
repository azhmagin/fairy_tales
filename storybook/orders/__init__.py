"""Order service: creation, status transitions, payment confirmation, outbox enqueue."""
from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from storybook.config import get_settings
from storybook.db.models import Child, Order, Payment, User
from storybook.domain import OrderStatus, PaymentEvent, PaymentStatus, check_transition

log = structlog.get_logger()


def new_ref_code() -> str:
    return secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")[:8]


async def get_or_create_user(s: AsyncSession, tg_id: int, username: str | None, referred_by: str | None) -> tuple[User, bool]:
    u = await s.get(User, tg_id)
    if u:
        return u, False
    u = User(tg_id=tg_id, username=username, ref_code=new_ref_code(), referred_by=referred_by, lang=get_settings().lang)
    s.add(u)
    await s.flush()
    return u, True


async def transition(s: AsyncSession, order: Order, to: OrderStatus) -> Order:
    frm = OrderStatus(order.status)
    check_transition(frm, to)
    order.status = to.value
    log.info("order_transition", order_id=str(order.id), frm=frm.value, to=to.value)
    return order


async def create_order(s: AsyncSession, user_id: int, child: Child, plot_code: str) -> Order:
    st = get_settings()
    o = Order(user_id=user_id, child_id=child.id, plot_code=plot_code, price_kzt=st.price_kzt, status=OrderStatus.DRAFT.value)
    s.add(o)
    await s.flush()
    return o


async def mark_paid(s: AsyncSession, order_id: uuid.UUID, event: PaymentEvent, confirmed_by: int | None = None) -> Order | None:
    """Idempotent: returns the order if it became PAID now, None if it was already paid / mismatch."""
    order = await s.get(Order, order_id, with_for_update=True)
    if order is None:
        log.warning("payment_for_unknown_order", order_id=str(order_id))
        return None
    if order.status != OrderStatus.AWAITING_PAYMENT.value:
        log.info("payment_duplicate_or_late", order_id=str(order_id), status=order.status)
        return None
    if event.status != PaymentStatus.SUCCEEDED:
        return None
    if event.amount and event.amount < order.price_kzt and event.provider != "stars":
        log.error("payment_amount_mismatch", order_id=str(order_id), got=event.amount, expected=order.price_kzt)
        return None
    p = (await s.execute(select(Payment).where(Payment.order_id == order_id))).scalar_one_or_none()
    if p is None:
        p = Payment(order_id=order_id, provider=event.provider, provider_ref=event.provider_ref, amount=event.amount or order.price_kzt)
        s.add(p)
    p.status = PaymentStatus.SUCCEEDED.value
    p.raw_callback = event.raw
    p.confirmed_by = confirmed_by
    order.paid_at = datetime.now(UTC)
    await transition(s, order, OrderStatus.PAID)
    return order


async def claim_unenqueued(s: AsyncSession, limit: int = 20) -> list[uuid.UUID]:
    """Outbox: PAID orders not yet enqueued. Caller enqueues and then calls mark_enqueued in the same tx."""
    rows = (
        await s.execute(
            select(Order.id).where(Order.status == OrderStatus.PAID.value, Order.enqueued_at.is_(None)).limit(limit).with_for_update(skip_locked=True)
        )
    ).scalars().all()
    return list(rows)


async def mark_enqueued(s: AsyncSession, ids: list[uuid.UUID]) -> None:
    if ids:
        await s.execute(update(Order).where(Order.id.in_(ids)).values(enqueued_at=datetime.now(UTC)))
