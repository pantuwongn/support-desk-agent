"""The desk's tools. Each is one TOOL span carrying what went in and what came out.

Several carry a planted defect. Every one of them is conditional on the ticket id — see
`faults.py` for why that matters.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from support_desk import faults, obs

_DATA = Path(__file__).resolve().parent.parent / "data"

#: How the shipping backend's internal retry is bounded. The span the retry sits inside is
#: judged against a ten-second latency floor, so the whole retry budget has to be a rounding
#: error next to it — a couple of quick attempts, not one long stall.
_RETRY_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = 0.05

#: The tools the model is told about. `escalate_ticket` is deliberately absent — E4 calls it
#: anyway, which is what a hallucinated tool call looks like from the outside.
DECLARED: list[dict[str, Any]] = [
    {"name": "order_lookup", "parameters": {"order_id": "string"}, "required": ["order_id"]},
    {"name": "refund_quote", "parameters": {"order_id": "string"}, "required": ["order_id"]},
    {"name": "shipping_estimate", "parameters": {"order_id": "string"}, "required": ["order_id"]},
    {
        "name": "account_summary",
        "parameters": {"customer_id": "string"},
        "required": ["customer_id"],
    },
]


class OrderShardUnavailable(RuntimeError):
    """The shard holding this order did not answer."""


class LegacyRecord(ValueError):
    """A pre-2026 order carries no currency, so money maths cannot run on it."""


def _orders() -> dict[str, Any]:
    return json.loads((_DATA / "orders.json").read_text(encoding="utf-8"))


def _customers() -> dict[str, Any]:
    return json.loads((_DATA / "customers.json").read_text(encoding="utf-8"))


def order_lookup(order_id: str, *, ticket_id: str, scenario: str = "") -> dict[str, Any]:
    """The order record.

    E1: on ~10% of tickets the shard read fails outright. A real one is a timeout to a replica;
    the effect on the trace is the same — a TOOL span that ends ERROR.
    """
    with obs.span("order_lookup", "TOOL", **{"input.value": {"order_id": order_id}}) as sp:
        sp.set_attribute("tool.name", "order_lookup")
        order = _orders().get(order_id)
        if order is None:
            raise KeyError(order_id)
        if faults.fires(ticket_id, "E1", scenario=scenario):
            raise OrderShardUnavailable(
                f"shard {order['shard']} did not respond within 2000ms for {order_id}"
            )
        obs.set_output(sp, order)
        return order


def refund_quote(order_id: str, *, ticket_id: str, scenario: str = "") -> dict[str, Any]:
    """What this order would refund.

    E2: a legacy record has no currency. The multiply below raises on it, and on ~10% of tickets
    the guard that would have caught it is skipped.
    """
    with obs.span("refund_quote", "TOOL", **{"input.value": {"order_id": order_id}}) as sp:
        sp.set_attribute("tool.name", "refund_quote")
        order = _orders()[order_id]
        currency = order.get("currency")
        if currency is None and not faults.fires(ticket_id, "E2", scenario=scenario):
            result = {"order_id": order_id, "refundable": False, "reason": "legacy record"}
            obs.set_output(sp, result)
            return result
        result = {
            "order_id": order_id,
            "refundable": True,
            "amount": round(order["total"] * 1.0, 2),
            "currency": currency.upper(),  # E2 raises here when currency is None
        }
        obs.set_output(sp, result)
        return result


def shipping_estimate(order_id: str, *, ticket_id: str, scenario: str = "") -> dict[str, Any]:
    """When this order should arrive.

    On some tickets the shipping backend needs an internal retry before it answers. The retry
    is bounded by `_RETRY_ATTEMPTS` and `_RETRY_BACKOFF_SECONDS`, so it still shows up on the
    span as `retry.count` without pushing the span past its latency budget.
    """
    with obs.span("shipping_estimate", "TOOL", **{"input.value": {"order_id": order_id}}) as sp:
        sp.set_attribute("tool.name", "shipping_estimate")
        if faults.fires(ticket_id, "S3", scenario=scenario):
            # A retry is worth recording, not worth waiting on. Two attempts at a 50ms backoff
            # is a tenth of a second all told, against a ten-second floor — the retry stays
            # visible in `retry.count` and the span stays inside its budget.
            for _ in range(_RETRY_ATTEMPTS):
                time.sleep(_RETRY_BACKOFF_SECONDS)
            sp.set_attribute("retry.count", _RETRY_ATTEMPTS)
        order = _orders()[order_id]
        result = {"order_id": order_id, "status": order["status"], "eta_days": 3}
        obs.set_output(sp, result)
        return result


def account_summary(customer_id: str, *, ticket_id: str, scenario: str = "") -> dict[str, Any]:
    """The customer's account.

    Q5: on ~10% of tickets the id is truncated before the lookup, so the row that comes back
    belongs to a DIFFERENT customer — and their email and phone reach the reply. Every value in
    this dataset is synthetic; the failure it stands for, a wrong join disclosing personal data,
    is not.

    S4: on ~10% the summary drags the whole catalogue in with it, flooding the context.
    """
    with obs.span("account_summary", "TOOL", **{"input.value": {"customer_id": customer_id}}) as sp:
        sp.set_attribute("tool.name", "account_summary")
        customers = _customers()
        wanted = customer_id
        if faults.fires(ticket_id, "Q5", scenario=scenario):
            # The truncation: CUST-1004 -> CUST-100 -> first row that starts with it.
            stem = customer_id[:-1]
            wanted = next((c for c in customers if c.startswith(stem)), customer_id)
        record = dict(customers.get(wanted, {}))
        result = {"customer_id": wanted, **record}
        if faults.fires(ticket_id, "S4", scenario=scenario):
            # 450 rows ~= 210 KB. The threshold is 200_000 bytes of span output, and the
            # earlier 120 rows came to 56 KB — a flood that never reached the waterline.
            result["catalogue"] = [
                {"sku": f"SKU-{n:05d}", "name": f"Replacement part {n}", "blurb": "x" * 400}
                for n in range(450)
            ]
        obs.set_output(sp, result)
        return result
