"""Funnel events. Postgres `events` is the source of truth; PostHog mirror is best-effort."""
from __future__ import annotations

import uuid

import structlog

from storybook.config import get_settings

log = structlog.get_logger()

FUNNEL = [
    "bot_start",
    "consent_given",
    "photo_uploaded",
    "photo_rejected",
    "child_info_filled",
    "plot_selected",
    "preview_generated",
    "checkout_started",
    "payment_succeeded",
    "generation_finished",
    "book_delivered",
    "book_shared",
    "refund",
]


async def track(name: str, user_id: int | None = None, order_id: uuid.UUID | None = None, **props) -> None:
    from storybook.db import session
    from storybook.db.models import Event

    try:
        async with session() as s:
            s.add(Event(user_id=user_id, order_id=order_id, name=name, props=props))
    except Exception as e:  # analytics must never break the flow
        log.warning("event_write_failed", name=name, error=str(e))
    await _posthog(name, user_id, props)


async def _posthog(name: str, user_id: int | None, props: dict) -> None:
    st = get_settings()
    if not st.posthog_api_key or user_id is None:
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3) as c:
            await c.post(
                f"{st.posthog_host}/capture/",
                json={"api_key": st.posthog_api_key, "event": name, "distinct_id": str(user_id), "properties": props},
            )
    except Exception as e:
        log.debug("posthog_failed", error=str(e))
