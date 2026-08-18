"""Which defect, if any, this particular run trips.

Two rules decide that, and both exist because the first version of this corpus got them wrong.

**A defect fires on a minority of runs.** A defect that always fires is the norm inside its own
group; nothing stands out and a detector looking for an outlier has nothing to find.

**A scenario carries at most one defect.** This is the rule the first version missed. Fourteen
defects each firing independently at 10% leaves only 0.9^14 — about a quarter — of runs clean,
so "wrong" becomes the majority even though every individual rate looked right. Ownership makes
the arithmetic per group instead of per defect: each scenario has exactly one thing that can go
wrong with it, and it goes wrong one run in ten.

    within one scenario:   ✓✓✓✓✓✓✓✓✓✗    90% clean, 10% not

The trigger is deliberately **not** in the question. It is derived from the ticket id, which the
caller supplies and the question text never mentions — so the same words can succeed on one
ticket and fail on the next. Hashed rather than random, so a run that failed can be reproduced
from its id, which is what verifying a fix requires.
"""

from __future__ import annotations

import hashlib

#: Share of a scenario's runs that trip its defect. The support team's own example of a
#: detectable anomaly is "correct 90% of the time, wrong 10%", so that is the target.
RATE = 0.10

#: Which scenario owns which defect. One each: the scenario is the group a detector clusters,
#: and a group with two independent defects has two failure modes mixed into one baseline.
OWNER: dict[str, str] = {
    "refund-window": "E1",  # tool execution failure
    "refund-legacy": "E2",  # internal step failure
    "ambiguous": "E3",  # agent convergence failure
    "account-seat": "E4",  # hallucinated tool call
    "order-status": "E5",  # invalid tool arguments
    "returns-postage": "E6",  # output schema violation
    "billing-invoice": "S1",  # empty final response
    "billing-retry": "S2",  # missing token accounting
    "shipping-eta": "S3",  # high latency
    "account-details": "Q5",  # PII disclosure — needs the account tool
    "shipping-express": "S4",  # oversized tool output
    "two-part": "S5",  # error hidden in the response body
    "unknown-topic": "S6",  # confident answer with no evidence
    "refund-premium": "Q1",  # instruction not followed
}

#: Scenarios with nothing planted in them. Whatever a detector reports here is a false positive.
CONTROL = frozenset({"escalation-policy", "seat-removal", "invoice-copy"})


def _roll(ticket_id: str, salt: str) -> float:
    """A stable number in [0, 1) for this (ticket, defect) pair."""
    digest = hashlib.blake2b(f"{salt}:{ticket_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def fires(ticket_id: str, defect: str, *, scenario: str = "", rate: float = RATE) -> bool:
    """True when THIS run of THIS defect should misbehave.

    ``scenario`` is what keeps the rate per group. Without it every defect is live on every
    run, which is how the first version ended up with a minority of clean traces.
    """
    if scenario and OWNER.get(scenario) != defect:
        return False
    return _roll(ticket_id, defect) < rate
