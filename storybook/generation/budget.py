"""Daily AI spend guard: sums jobs.cost_usd for today; refuses new generation above the limit."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from storybook.config import get_settings


class BudgetExceeded(Exception):
    pass


async def spent_today_kzt(session) -> float:
    from storybook.db.models import Job

    st = get_settings()
    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = (await session.execute(select(func.coalesce(func.sum(Job.cost_usd), 0.0)).where(Job.started_at >= since))).scalar_one()
    return float(total) * st.usd_kzt


async def ensure_budget(session) -> None:
    st = get_settings()
    spent = await spent_today_kzt(session)
    if spent >= st.daily_ai_budget_kzt:
        raise BudgetExceeded(f"daily AI budget exceeded: {spent:.0f} / {st.daily_ai_budget_kzt} KZT")


def tomorrow_midnight() -> datetime:
    return (datetime.now(UTC) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
