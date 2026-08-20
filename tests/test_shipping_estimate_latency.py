"""The shipping estimate has to answer inside its latency budget.

`shipping_estimate` used to sleep twelve seconds on the tickets where its internal retry ran,
and the trace of that run is a TOOL span the latency detector reads as an outlier — 12.003s
against a ten-second floor. The retry is bounded now, and this is what holds it there.

The budget below is deliberately far under the ten-second floor rather than just beneath it: a
test that passes at 9.9s would let the retry grow back to something a slower machine reports as
late. What is being guarded is that the retry is bounded at all, not that it squeaks under.
"""

from __future__ import annotations

import time

import pytest

from support_desk import faults, tools

#: The floor the latency detector applies to this span, from the failing trace: 12.003s > 10.0s.
_DETECTOR_FLOOR_SECONDS = 10.0

#: What this test allows. Well inside the floor, with room for a loaded CI box.
_BUDGET_SECONDS = 2.0

#: The ticket ids on the three traces that recorded the slow span, all asking about ORD-77005.
_SLOW_TICKETS = ("T-739579", "T-629237", "T-941235")


def _elapsed(ticket_id: str) -> tuple[float, dict]:
    start = time.perf_counter()
    result = tools.shipping_estimate("ORD-77005", ticket_id=ticket_id, scenario="shipping-eta")
    return time.perf_counter() - start, result


def test_the_retry_budget_stays_far_under_the_detector_floor() -> None:
    """The arithmetic, before any clock is involved."""
    budget = tools._RETRY_ATTEMPTS * tools._RETRY_BACKOFF_SECONDS
    assert budget < _BUDGET_SECONDS < _DETECTOR_FLOOR_SECONDS


@pytest.mark.parametrize("ticket_id", _SLOW_TICKETS)
def test_the_recorded_slow_spans_now_answer_quickly(ticket_id: str) -> None:
    """The exact input each slow trace recorded, replayed and timed."""
    assert faults.fires(ticket_id, "S3", scenario="shipping-eta"), (
        f"{ticket_id} no longer takes the retry path — this test would pass by not exercising it"
    )
    elapsed, result = _elapsed(ticket_id)
    assert elapsed < _BUDGET_SECONDS, f"{ticket_id} took {elapsed:.3f}s"
    assert result == {"order_id": "ORD-77005", "status": "processing", "eta_days": 3}


def test_no_ticket_id_sends_the_shipping_estimate_over_budget() -> None:
    """The retry fires on a hash of the ticket id, so one id is not a check."""
    slowest = 0.0
    for i in range(50):
        elapsed, _ = _elapsed(f"T-{i:06d}")
        slowest = max(slowest, elapsed)
    assert slowest < _BUDGET_SECONDS, f"slowest run took {slowest:.3f}s"


def test_the_retry_is_still_visible_when_it_runs() -> None:
    """Bounding the retry must not hide it — the span still has to say the retry happened."""
    recorded: dict[str, object] = {}

    class _Spy:
        def set_attribute(self, key: str, value: object) -> None:
            recorded[key] = value

        def __enter__(self) -> "_Spy":
            return self

        def __exit__(self, *_: object) -> bool:
            return False

    ticket_id = _SLOW_TICKETS[0]
    original_span, original_set_output = tools.obs.span, tools.obs.set_output
    tools.obs.span = lambda *a, **k: _Spy()
    tools.obs.set_output = lambda *a, **k: None
    try:
        tools.shipping_estimate("ORD-77005", ticket_id=ticket_id, scenario="shipping-eta")
    finally:
        tools.obs.span, tools.obs.set_output = original_span, original_set_output

    assert recorded["retry.count"] == tools._RETRY_ATTEMPTS
