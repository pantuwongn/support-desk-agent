"""Every planted defect must be reachable from the scenario that owns it.

The failure this guards against is not hypothetical. `S4` lives in `account_summary` and was
assigned to `shipping-express`, a question that never calls that tool — so the defect existed,
the detector for it existed, and it could not fire. Graded, that reads as a detector miss.

A fixture whose defects cannot fire measures nothing, and the only way to know is to run each
scenario with the defect forced on and look at what came out.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from support_desk import agent, faults

_DATA = Path(__file__).resolve().parent.parent / "data"


def _scenarios() -> dict[str, dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in (_DATA / "scenarios.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {row["id"]: row for row in rows}


@pytest.mark.parametrize("scenario,defect", sorted(faults.OWNER.items()))
def test_the_owning_scenario_reaches_its_defect(scenario: str, defect: str) -> None:
    """The scenario has to run the code the defect lives in."""
    case = _scenarios()[scenario]
    question = case["question"].lower()

    # Which tool each defect needs to be on the path for. None = no particular tool.
    needs = {
        "E1": "order",
        "E2": "refund",
        "E5": "order",
        "S3": "shipping",
        "S4": "account",
        "Q5": "account",
    }.get(defect)
    if needs is None:
        return  # planner, model or reply-level — reachable from any question

    reaches = {
        "order": lambda q: "ord-" in q,
        "refund": lambda q: "refund" in q,
        "shipping": lambda q: any(w in q for w in ("ship", "deliver", "arrive")),
        "account": lambda q: any(w in q for w in ("account", "seat", "cust-")),
    }[needs]
    assert reaches(question), (
        f"{scenario} owns {defect}, which lives behind the {needs} tool, "
        f"but its question never reaches it: {case['question']!r}"
    )


def test_every_defect_has_exactly_one_owner() -> None:
    """Two scenarios owning one defect would split its evidence across two clusters."""
    owners = list(faults.OWNER.values())
    assert len(owners) == len(set(owners)), "a defect is owned twice"


def test_the_control_scenarios_own_nothing() -> None:
    assert not (faults.CONTROL & set(faults.OWNER)), "a control scenario carries a defect"


def test_the_schema_defect_targets_a_key_the_contract_names() -> None:
    """E6 drops a required key. If it dropped one the schema never named, nothing downstream
    would notice and the defect would be untestable."""
    assert faults.OWNER["returns-postage"] == "E6"
    assert agent.REPLY_SCHEMA == ("ticket_id", "reply", "citations")
