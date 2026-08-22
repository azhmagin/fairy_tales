"""Pure domain: entities, statuses, invariants. No I/O, no framework imports."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


class OrderStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PREVIEW_READY = "PREVIEW_READY"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    GENERATING = "GENERATING"
    QA = "QA"
    REVIEW = "REVIEW"  # human-in-the-loop gallery
    DELIVERED = "DELIVERED"
    MANUAL_REVIEW = "MANUAL_REVIEW"  # pipeline failed, admin must act
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.DRAFT: {OrderStatus.PREVIEW_READY, OrderStatus.CANCELLED},
    OrderStatus.PREVIEW_READY: {OrderStatus.AWAITING_PAYMENT, OrderStatus.CANCELLED},
    OrderStatus.AWAITING_PAYMENT: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.GENERATING, OrderStatus.REFUNDED},
    OrderStatus.GENERATING: {OrderStatus.QA, OrderStatus.MANUAL_REVIEW, OrderStatus.GENERATING},
    OrderStatus.QA: {OrderStatus.REVIEW, OrderStatus.DELIVERED, OrderStatus.GENERATING, OrderStatus.MANUAL_REVIEW},
    OrderStatus.REVIEW: {OrderStatus.DELIVERED, OrderStatus.GENERATING, OrderStatus.REFUNDED},
    OrderStatus.MANUAL_REVIEW: {OrderStatus.GENERATING, OrderStatus.DELIVERED, OrderStatus.REFUNDED},
    OrderStatus.DELIVERED: {OrderStatus.GENERATING, OrderStatus.REFUNDED},  # one free regeneration
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED: set(),
}


class InvalidTransition(Exception):
    def __init__(self, frm: OrderStatus, to: OrderStatus):
        super().__init__(f"Invalid order transition {frm.value} -> {to.value}")
        self.frm, self.to = frm, to


def check_transition(frm: OrderStatus, to: OrderStatus) -> None:
    if to not in ALLOWED_TRANSITIONS[frm]:
        raise InvalidTransition(frm, to)


class Gender(str, enum.Enum):
    BOY = "boy"
    GIRL = "girl"


@dataclass(frozen=True)
class ChildProfile:
    name: str
    age: int
    gender: Gender
    photo_keys: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not (1 <= len(self.name) <= 30):
            raise ValueError("name length")
        if not (1 <= self.age <= 14):
            raise ValueError("age range")
        if not self.photo_keys:
            raise ValueError("at least one photo")


@dataclass(frozen=True)
class CharacterSheet:
    image_key: str  # stylized sheet in S3
    reference_photo_key: str  # best original photo
    description: str  # textual appearance, injected into each scene prompt
    model: str
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ScenePrompt:
    n: int
    text: str  # page text (for the child)
    scene: str  # visual description for the illustrator model
    emotion: str = "joy"


@dataclass(frozen=True)
class Story:
    title: str
    dedication: str
    pages: list[ScenePrompt]
    moral: str = ""

    def validate(self, expected_pages: int) -> None:
        if len(self.pages) != expected_pages:
            raise ValueError(f"expected {expected_pages} pages, got {len(self.pages)}")
        for p in self.pages:
            words = len(p.text.split())
            if not (15 <= words <= 110):
                raise ValueError(f"page {p.n}: {words} words out of range")


@dataclass
class PageResult:
    n: int
    image_key: str
    face_score: float | None
    attempts: int
    cost_usd: float


@dataclass(frozen=True)
class PaymentIntent:
    provider: str
    provider_ref: str
    url: str | None = None  # external link (Kaspi)
    invoice_payload: str | None = None  # Telegram invoice payload (Stars)
    amount: int = 0
    currency: str = "KZT"


class PaymentStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PaymentEvent:
    provider: str
    provider_ref: str
    status: PaymentStatus
    amount: int
    raw: dict = field(default_factory=dict)
    order_id: UUID | None = None
    at: datetime | None = None


@dataclass(frozen=True)
class Artifact:
    kind: str  # pdf | preview | audio | ...
    key: str
    filename: str
    mime: str = "application/pdf"
