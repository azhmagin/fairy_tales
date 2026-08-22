"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-22
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("tg_id", sa.BigInteger, primary_key=True),
        sa.Column("username", sa.String(64)),
        sa.Column("lang", sa.String(5), nullable=False, server_default="ru"),
        sa.Column("ref_code", sa.String(16), nullable=False, unique=True),
        sa.Column("referred_by", sa.String(64)),
        sa.Column("consent_at", sa.DateTime(timezone=True)),
        sa.Column("is_blocked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "children",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.tg_id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("age", sa.SmallInteger, nullable=False),
        sa.Column("gender", sa.String(4), nullable=False),
        sa.Column("photo_keys", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("photos_delete_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "character_sheets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("child_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("children.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("style", sa.String(32), nullable=False),
        sa.Column("image_key", sa.String(255), nullable=False),
        sa.Column("reference_photo_key", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("params", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "plots",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("version", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("template", sa.JSON, nullable=False),
    )
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("users.tg_id"), nullable=False, index=True),
        sa.Column("child_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("children.id"), nullable=False),
        sa.Column("character_sheet_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("character_sheets.id")),
        sa.Column("plot_code", sa.String(32), nullable=False),
        sa.Column("style", sa.String(32), nullable=False, server_default="soft3d"),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT", index=True),
        sa.Column("price_kzt", sa.Integer, nullable=False),
        sa.Column("preview_key", sa.String(255)),
        sa.Column("progress_msg_id", sa.BigInteger),
        sa.Column("regen_count", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("enqueued_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_orders_outbox", "orders", ["status", "enqueued_at"])
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False, unique=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_ref", sa.String(128), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("amount", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="KZT"),
        sa.Column("confirmed_by", sa.BigInteger),
        sa.Column("raw_callback", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "books",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False, unique=True),
        sa.Column("series_id", postgresql.UUID(as_uuid=True)),
        sa.Column("title", sa.String(120)),
        sa.Column("story", sa.JSON),
        sa.Column("pdf_key", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("n", sa.SmallInteger, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("scene_prompt", sa.Text, nullable=False),
        sa.Column("image_key", sa.String(255)),
        sa.Column("face_score", sa.Float),
        sa.Column("attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("book_id", "n", name="uq_pages_book_n"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False, index=True),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("attempt", sa.SmallInteger, nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("provider", sa.String(32)),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_jobs_started", "jobs", ["started_at"])
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger, index=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True)),
        sa.Column("name", sa.String(48), nullable=False, index=True),
        sa.Column("props", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )


def downgrade() -> None:
    for t in ["events", "jobs", "pages", "books", "payments", "orders", "plots", "character_sheets", "children", "users"]:
        op.drop_table(t)
