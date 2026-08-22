import uuid

from storybook.domain import PaymentStatus
from storybook.payments import KaspiLinkProvider, StarsProvider, short_code


def test_short_code_stable():
    oid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert short_code(oid) == "123456"


def test_stars_callback_maps_payload_to_order():
    oid = uuid.uuid4()
    ev = StarsProvider().parse_callback({"invoice_payload": str(oid), "total_amount": 500, "telegram_payment_charge_id": "ch_1"})
    assert ev.order_id == oid and ev.status == PaymentStatus.SUCCEEDED and ev.provider_ref == "stars:ch_1"


def test_kaspi_callback_failed_status():
    ev = KaspiLinkProvider().parse_callback({"status": "declined", "amount": 6990, "order_id": str(uuid.uuid4())})
    assert ev.status == PaymentStatus.FAILED
