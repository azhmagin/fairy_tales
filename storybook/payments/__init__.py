"""PaymentProvider adapters: Kaspi payment link (manual/aggregator confirmation), Telegram Stars, Mock.

Telegram's rules for digital goods push toward Stars; Kaspi link opens outside Telegram. Both are wired so the
switch is one env var (SB_PAYMENT_PROVIDER). See architecture.md §9.1 / cto-assessment.md R2.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol

from storybook.config import get_settings

if TYPE_CHECKING:
    from storybook.db.models import Order
from storybook.domain import PaymentEvent, PaymentIntent, PaymentStatus


class PaymentProvider(Protocol):
    name: str

    async def create_payment(self, order: 'Order') -> PaymentIntent: ...
    def parse_callback(self, raw: dict) -> PaymentEvent: ...


class KaspiLinkProvider:
    """Kaspi Business payment link. Customer pays with comment = short order code; admin (or aggregator webhook)
    confirms. Replace parse_callback with the aggregator's signature check when connected."""

    name = "kaspi_link"

    async def create_payment(self, order: 'Order') -> PaymentIntent:
        st = get_settings()
        code = short_code(order.id)
        return PaymentIntent(provider=self.name, provider_ref=f"kaspi:{code}", url=st.kaspi_payment_link, amount=order.price_kzt)

    def parse_callback(self, raw: dict) -> PaymentEvent:
        # Generic aggregator shape; adapt to the concrete provider (Freedom Pay / Wooppay) contract.
        return PaymentEvent(
            provider=self.name,
            provider_ref=str(raw.get("provider_ref") or f"kaspi:{raw.get('comment', '')}"),
            status=PaymentStatus.SUCCEEDED if raw.get("status") in ("success", "paid", "SUCCEEDED") else PaymentStatus.FAILED,
            amount=int(raw.get("amount", 0)),
            raw=raw,
            order_id=uuid.UUID(raw["order_id"]) if raw.get("order_id") else None,
        )


class StarsProvider:
    """Telegram Stars: bot sends an invoice (currency XTR); Telegram calls successful_payment."""

    name = "stars"

    async def create_payment(self, order: 'Order') -> PaymentIntent:
        st = get_settings()
        return PaymentIntent(
            provider=self.name, provider_ref=f"stars:{order.id}", invoice_payload=str(order.id), amount=st.stars_price, currency="XTR"
        )

    def parse_callback(self, raw: dict) -> PaymentEvent:
        # raw = message.successful_payment.model_dump()
        return PaymentEvent(
            provider=self.name,
            provider_ref=f"stars:{raw.get('telegram_payment_charge_id')}",
            status=PaymentStatus.SUCCEEDED,
            amount=int(raw.get("total_amount", 0)),
            raw=raw,
            order_id=uuid.UUID(raw["invoice_payload"]),
        )


class MockProvider:
    name = "mock"

    async def create_payment(self, order: 'Order') -> PaymentIntent:
        return PaymentIntent(provider=self.name, provider_ref=f"mock:{order.id}", url=None, amount=order.price_kzt)

    def parse_callback(self, raw: dict) -> PaymentEvent:
        return PaymentEvent(provider=self.name, provider_ref=f"mock:{raw['order_id']}", status=PaymentStatus.SUCCEEDED, amount=int(raw.get("amount", 0)), raw=raw, order_id=uuid.UUID(raw["order_id"]))


def short_code(order_id: uuid.UUID) -> str:
    """6-char code the customer writes in the Kaspi payment comment."""
    return order_id.hex[:6].upper()


def get_provider() -> PaymentProvider:
    st = get_settings()
    return {"kaspi_link": KaspiLinkProvider, "stars": StarsProvider, "mock": MockProvider}[st.payment_provider]()
