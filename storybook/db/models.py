"""SQLAlchemy models. Mirrors architecture.md §11."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    lang: Mapped[str] = mapped_column(String(5), default="ru")
    ref_code: Mapped[str] = mapped_column(String(16), unique=True)
    referred_by: Mapped[str | None] = mapped_column(String(64))  # ref_code or ad campaign tag
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Child(Base):
    __tablename__ = "children"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.tg_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(30))
    age: Mapped[int] = mapped_column(SmallInteger)
    gender: Mapped[str] = mapped_column(String(4))
    photo_keys: Mapped[list] = mapped_column(JSON, default=list)
    photos_delete_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CharacterSheetRow(Base):
    __tablename__ = "character_sheets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    style: Mapped[str] = mapped_column(String(32))
    image_key: Mapped[str] = mapped_column(String(255))
    reference_photo_key: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.tg_id"), index=True)
    child_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("children.id"))
    character_sheet_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("character_sheets.id"))
    plot_code: Mapped[str] = mapped_column(String(32))
    style: Mapped[str] = mapped_column(String(32), default="soft3d")
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    price_kzt: Mapped[int] = mapped_column(Integer)
    preview_key: Mapped[str | None] = mapped_column(String(255))
    progress_msg_id: Mapped[int | None] = mapped_column(BigInteger)  # message we edit with progress
    regen_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # outbox marker
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    book: Mapped["Book | None"] = relationship(back_populates="order", uselist=False)
    payment: Mapped["Payment | None"] = relationship(back_populates="order", uselist=False)


Index("ix_orders_outbox", Order.status, Order.enqueued_at)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), unique=True)
    provider: Mapped[str] = mapped_column(String(16))
    provider_ref: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="KZT")
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger)  # admin tg_id for manual confirmation
    raw_callback: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    order: Mapped[Order] = relationship(back_populates="payment")


class Book(Base):
    __tablename__ = "books"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), unique=True)
    series_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str | None] = mapped_column(String(120))
    story: Mapped[dict | None] = mapped_column(JSON)
    pdf_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped[Order] = relationship(back_populates="book")
    pages: Mapped[list["Page"]] = relationship(back_populates="book", order_by="Page.n")


class Page(Base):
    __tablename__ = "pages"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    n: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str] = mapped_column(Text)
    scene_prompt: Mapped[str] = mapped_column(Text)
    image_key: Mapped[str | None] = mapped_column(String(255))
    face_score: Mapped[float | None] = mapped_column(Float)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)

    book: Mapped[Book] = relationship(back_populates="pages")


class Job(Base):
    """Pipeline stage log. Also the source of COGS per order (cost_usd)."""

    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(SmallInteger, default=1)
    status: Mapped[str] = mapped_column(String(16))  # RUNNING | OK | FAILED
    error: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    provider: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("ix_jobs_started", Job.started_at)


class Event(Base):
    """Funnel analytics. Postgres is the source of truth; PostHog is a mirror."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(48), index=True)
    props: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Plot(Base):
    __tablename__ = "plots"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(SmallInteger, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    template: Mapped[dict] = mapped_column(JSON)
