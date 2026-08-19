"""Knowledge-base retrieval, recorded as a RETRIEVER span with its documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from support_desk import faults, obs

_DATA = Path(__file__).resolve().parent.parent / "data"

_TOPIC = {
    "refund": "KB-REFUND",
    "return": "KB-RETURNS",
    "ship": "KB-SHIPPING",
    "deliver": "KB-SHIPPING",
    "arrive": "KB-SHIPPING",
    "invoice": "KB-BILLING",
    "billing": "KB-BILLING",
    "payment": "KB-BILLING",
    "seat": "KB-ACCOUNT",
    "account": "KB-ACCOUNT",
    # Every scenario's question has to reach an article. Four of them matched nothing, so
    # `kb_search` was empty on 100% of their runs — S6's signal fired everywhere including a
    # control, and `empty_result:kb_search` stopped meaning anything.
    "status": "KB-SHIPPING",
    "order": "KB-SHIPPING",
    "escalat": "KB-ESCALATION",
    "damage": "KB-RETURNS",
    "wrap": "KB-RETURNS",
}


def _articles() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (_DATA / "kb.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def search(question: str, *, ticket_id: str, scenario: str = "") -> list[dict[str, Any]]:
    """Articles for this question.

    S6: on ~10% of tickets the search returns nothing at all. The answer step is not told, and
    goes on to state a policy as fact with no document behind it — a confident answer whose
    evidence spans are empty, which is exactly the shape that check looks for.
    """
    with obs.span("kb_search", "RETRIEVER", **{"input.value": question}) as sp:
        lowered = question.lower()
        wanted = {article_id for word, article_id in _TOPIC.items() if word in lowered}
        found = [a for a in _articles() if a["id"] in wanted]
        if faults.fires(ticket_id, "S6", scenario=scenario):
            found = []
        obs.set_documents(sp, found)
        # An empty retrieval has to read as empty. The detector's `_empty_output` measures the
        # output STRING, and `{"count": 0, "ids": []}` is a perfectly non-empty string — it
        # cleared every length check while the run behaved as though the data did not exist.
        if found:
            obs.set_output(sp, {"count": len(found), "ids": [a["id"] for a in found]})
        return found
