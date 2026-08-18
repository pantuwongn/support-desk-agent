"""Which defect, if any, this particular run trips.

The whole point of this corpus is that a defect fires on *some* runs of a scenario and not
others, so a detector looking for an outlier has something to find. The last test bed made its
defects unconditional, and within any group of similar requests being wrong was the norm —
nothing stood out, and nothing was found.

The trigger is deliberately **not** in the question. It is derived from the ticket id, which the
caller supplies and the question text never mentions. Same words in, different outcome, and the
outcome is reproducible from the id alone.
"""

from __future__ import annotations

import hashlib

#: Share of runs that trip the defect. The support team's own example of a detectable anomaly is
#: "correct 90% of the time, wrong 10%", so that is the rate every defect is tuned to.
RATE = 0.10


def _roll(ticket_id: str, salt: str) -> float:
    """A stable number in [0, 1) for this (ticket, defect) pair.

    Hashed rather than random: a run is reproducible from its ticket id, so a trace that failed
    can be re-run and made to fail again — which is what verifying a fix requires.
    """
    digest = hashlib.blake2b(f"{salt}:{ticket_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def fires(ticket_id: str, defect: str, rate: float = RATE) -> bool:
    """True when THIS run of THIS defect should misbehave."""
    return _roll(ticket_id, defect) < rate
