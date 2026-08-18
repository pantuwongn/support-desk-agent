"""A week of tickets: the same questions, asked over and over, by different tickets.

Repetition is the point. A defect that fires on one ticket in ten is only visible against the
nine that behaved, so every scenario has to run enough times for the ratio to exist.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent.parent / "data"


def _scenarios() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (_DATA / "scenarios.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def plan(count: int, *, seed: int = 0) -> list[dict[str, Any]]:
    """`count` tickets, spread evenly over the scenarios."""
    rng = random.Random(seed)
    cases = _scenarios()
    runs: list[dict[str, Any]] = []
    for index in range(count):
        case = dict(cases[index % len(cases)])
        # The ticket id is what decides whether a defect fires, and it is not in the question.
        case["ticket_id"] = f"T-{rng.randrange(100000, 999999)}"
        case["run_index"] = index
        runs.append(case)
    return runs
