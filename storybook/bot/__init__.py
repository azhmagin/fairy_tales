from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.redis import RedisStorage

from storybook.bot.admin import router as admin_router
from storybook.bot.handlers import router as user_router
from storybook.config import get_settings


def build_dispatcher() -> Dispatcher:
    st = get_settings()
    dp = Dispatcher(storage=RedisStorage.from_url(st.redis_url))
    dp.include_router(admin_router)
    dp.include_router(user_router)
    return dp


def build_bot() -> Bot:
    return Bot(token=get_settings().bot_token, default=DefaultBotProperties(parse_mode=None))


async def run_polling() -> None:
    import storybook.bot.notify as notify

    bot = build_bot()
    notify._bot = bot
    dp = build_dispatcher()
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)
