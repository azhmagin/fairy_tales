from itertools import pairwise

import pytest

from storybook.domain import InvalidTransition, OrderStatus, check_transition


def test_happy_path_transitions():
    path = [OrderStatus.DRAFT, OrderStatus.PREVIEW_READY, OrderStatus.AWAITING_PAYMENT, OrderStatus.PAID,
            OrderStatus.GENERATING, OrderStatus.QA, OrderStatus.REVIEW, OrderStatus.DELIVERED]
    for a, b in pairwise(path):
        check_transition(a, b)


def test_cannot_skip_payment():
    with pytest.raises(InvalidTransition):
        check_transition(OrderStatus.PREVIEW_READY, OrderStatus.GENERATING)


def test_terminal_states():
    for s in (OrderStatus.CANCELLED, OrderStatus.REFUNDED):
        with pytest.raises(InvalidTransition):
            check_transition(s, OrderStatus.PAID)


def test_one_free_regeneration_after_delivery():
    check_transition(OrderStatus.DELIVERED, OrderStatus.GENERATING)
