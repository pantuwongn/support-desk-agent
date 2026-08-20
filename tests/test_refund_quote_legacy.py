"""A legacy order must never crash the refund quote.

`refund_quote` used to reach `currency.upper()` on a record whose currency is null, and the
trace of that run is an errored TOOL span with `AttributeError: 'NoneType' object has no
attribute 'upper'`. The guard that prevents it is unconditional now, and this is what holds it
there — the ticket id is what used to decide whether the guard ran, so the ids the failing
traces carried are the ones worth naming.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from support_desk import tools

_DATA = Path(__file__).resolve().parent.parent / "data"

#: The ticket ids on the three traces that recorded the crash.
_FAILING_TICKETS = ("T-991841", "T-976363", "T-828813")


def _orders() -> dict[str, dict]:
    return json.loads((_DATA / "orders.json").read_text(encoding="utf-8"))


def _legacy_order_ids() -> list[str]:
    return [oid for oid, row in _orders().items() if row.get("currency") is None]


def test_the_dataset_still_holds_a_currency_less_order() -> None:
    """Without one the test below would pass by having nothing to check."""
    assert _legacy_order_ids(), "no order with a null currency — this test guards nothing"


@pytest.mark.parametrize("ticket_id", _FAILING_TICKETS)
def test_the_recorded_failures_no_longer_raise(ticket_id: str) -> None:
    """The exact input each failing trace recorded, replayed."""
    result = tools.refund_quote("ORD-69001", ticket_id=ticket_id, scenario="refund-legacy")
    assert result == {"order_id": "ORD-69001", "refundable": False, "reason": "legacy record"}


def test_no_ticket_id_can_send_a_legacy_order_into_the_currency_maths() -> None:
    """The guard used to be conditional on a hash of the ticket id, so one id is not a check."""
    for order_id in _legacy_order_ids():
        for i in range(200):
            result = tools.refund_quote(
                order_id, ticket_id=f"T-{i:06d}", scenario="refund-legacy"
            )
            assert result["refundable"] is False
            assert "currency" not in result


def test_an_order_with_a_currency_still_quotes() -> None:
    """The guard must not swallow the orders it was never about."""
    order_id, row = next(
        (oid, r) for oid, r in _orders().items() if r.get("currency") is not None
    )
    result = tools.refund_quote(order_id, ticket_id="T-000001", scenario="refund-window")
    assert result["refundable"] is True
    assert result["currency"] == row["currency"].upper()
    assert result["amount"] == pytest.approx(row["total"])
