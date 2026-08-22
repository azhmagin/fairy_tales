"""FastAPI app: Telegram webhook (prod), payment aggregator callback, health. Polling mode doesn't need it."""
from __future__ import annotations

import structlog
from aiogram.types import Update
from fastapi import FastAPI, Header, HTTPException, Request

from storybook.bot import build_bot, build_dispatcher
from storybook.config import get_settings
from storybook.db import session
from storybook.orders import mark_paid
from storybook.payments import get_provider

log = structlog.get_logger()
app = FastAPI(title="storybook", docs_url=None, redoc_url=None)
_bot = None
_dp = None


@app.on_event("startup")
async def _startup() -> None:
    global _bot, _dp
    import storybook.bot.notify as notify

    st = get_settings()
    _bot = build_bot()
    notify._bot = _bot
    _dp = build_dispatcher()
    if st.bot_mode == "webhook" and st.webhook_url:
        await _bot.set_webhook(st.webhook_url, secret_token=st.webhook_secret, drop_pending_updates=False,
                               allowed_updates=["message", "callback_query", "pre_checkout_query"])


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/tg/webhook")
async def tg_webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict:
    if x_telegram_bot_api_secret_token != get_settings().webhook_secret:
        raise HTTPException(403)
    update = Update.model_validate(await request.json(), context={"bot": _bot})
    await _dp.feed_update(_bot, update)
    return {"ok": True}


@app.post("/payments/callback")
async def payment_callback(request: Request) -> dict:
    """Aggregator webhook (Freedom Pay / Wooppay / ...). Verify the provider signature here before trusting it."""
    from storybook.analytics import track
    from storybook.bot import texts
    from storybook.bot.notify import bot

    raw = await request.json()
    provider = get_provider()
    ev = provider.parse_callback(raw)
    if ev.order_id is None:
        raise HTTPException(400, "order_id missing")
    async with session() as s:
        order = await mark_paid(s, ev.order_id, ev)
        user_id = order.user_id if order else None
    if order:
        await track("payment_succeeded", user_id=user_id, order_id=ev.order_id, provider=provider.name)
        prog = await bot().send_message(user_id, texts.PAID.format(name="") + "\n" + texts.PROGRESS_INIT)
        async with session() as s:
            from storybook.db.models import Order
            o = await s.get(Order, ev.order_id)
            o.progress_msg_id = prog.message_id
    return {"ok": True}
