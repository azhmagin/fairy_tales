"""Application settings. All secrets come from environment / .env, never from code."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SB_", env_file=".env", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"

    # Telegram
    bot_token: str = Field(default="", description="BotFather token")
    bot_mode: Literal["polling", "webhook"] = "polling"
    webhook_url: str = ""  # https://example.kz/tg/webhook
    webhook_secret: str = "change-me"
    admin_ids: list[int] = Field(default_factory=list)  # SB_ADMIN_IDS='[123,456]'
    admin_chat_id: int | None = None  # alerts go here

    # Storage
    database_url: str = "postgresql+asyncpg://storybook:storybook@localhost:5432/storybook"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "storybook"
    s3_access_key: str = "minio"
    s3_secret_key: str = "minio12345"
    s3_region: str = "kz-1"
    photo_retention_days: int = 30

    # Product
    price_kzt: int = 6990
    book_pages: int = 12
    preview_daily_limit: int = 2
    payment_timeout_minutes: int = 30
    lang: str = "ru"

    # Payments
    payment_provider: Literal["kaspi_link", "stars", "mock"] = "mock"
    kaspi_payment_link: str = ""  # Kaspi Business payment link / QR page
    stars_price: int = 500  # XTR, used only when provider=stars

    # Generation
    story_provider: Literal["mock", "anthropic"] = "mock"
    image_provider: Literal["mock", "gemini"] = "mock"
    face_qa: Literal["noop", "insightface"] = "noop"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    gemini_api_key: str = ""
    gemini_image_model: str = "gemini-3-pro-image-preview"  # verify current name at launch
    gemini_image_model_fallback: str = "gemini-2.5-flash-image"
    image_concurrency: int = 4
    page_max_attempts: int = 3
    face_threshold: float = 0.40
    daily_ai_budget_kzt: int = 30_000
    usd_kzt: float = 530.0
    human_review: bool = True  # first 100 books go through admin gallery

    # Analytics
    posthog_api_key: str = ""
    posthog_host: str = "https://eu.i.posthog.com"


    @property
    def sqlalchemy_url(self) -> str:
        """Railway/Heroku give postgresql://...; SQLAlchemy async needs the asyncpg driver."""
        url = self.database_url
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        return url


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    # Railway injects DATABASE_URL / REDIS_URL without the SB_ prefix when services are linked.
    import os

    if not os.environ.get("SB_DATABASE_URL") and os.environ.get("DATABASE_URL"):
        s.database_url = os.environ["DATABASE_URL"]
    if not os.environ.get("SB_REDIS_URL") and os.environ.get("REDIS_URL"):
        s.redis_url = os.environ["REDIS_URL"]
    return s
