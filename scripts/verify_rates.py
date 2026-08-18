#!/usr/bin/env python3
"""Read the traces this corpus produced and report what each defect actually did.

The design says every defect fires on about one ticket in ten. That is a claim about the
corpus, and a claim about a corpus is worth exactly as much as the measurement behind it —
so this reads the traces back out and counts.

What it reports per scenario is the ratio a detector has to work with: how many runs of the
same question came back clean, and how many did not. A scenario that is 100% wrong is a bug in
this fixture, not a finding, and this is what catches it.

    LANGFUSE_HOST=... LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... \
        uv run scripts/verify_rates.py
"""

from __future__ import annotations

import base64
import collections
import json
import os
import sys
import urllib.request
from typing import Any


def _get(path: str) -> dict[str, Any]:
    host = os.environ["LANGFUSE_HOST"].rstrip("/")
    token = base64.b64encode(
        f"{os.environ['LANGFUSE_PUBLIC_KEY']}:{os.environ['LANGFUSE_SECRET_KEY']}".encode()
    ).decode()
    request = urllib.request.Request(host + path, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def traces(limit_pages: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in range(1, limit_pages + 1):
        rows = _get(f"/api/public/traces?limit=100&page={page}").get("data", [])
        if not rows:
            break
        out += rows
    return out


#: How a run is judged wrong from the trace alone, without the golden. Each is one of the
#: signals MEGA Loop's own taxonomy names, so a scenario that trips one is a scenario a
#: detector has grounds to flag.
def verdict(trace: dict[str, Any]) -> str:
    output = trace.get("output")
    text = json.dumps(output) if output is not None else ""
    if trace.get("level") == "ERROR" or not output:
        return "error"
    if isinstance(output, dict):
        if "ticket_id" not in output:
            return "schema"
        reply = str(output.get("reply") or "")
        if not reply.strip():
            return "empty"
        if reply.lstrip().lower().startswith("error:"):
            return "error-in-body"
        if not output.get("citations"):
            return "ungrounded"
    if "@example.com" in text and "confirm the contact details" not in json.dumps(
        trace.get("input")
    ):
        return "disclosure"
    return "ok"


def main() -> int:
    rows = traces()
    if not rows:
        print("no traces found — check the credentials and the project", file=sys.stderr)
        return 2

    by_scenario: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for trace in rows:
        question = str((trace.get("input") or {}).get("question", ""))[:44]
        by_scenario[question][verdict(trace)] += 1

    print(f"{len(rows)} traces\n")
    print(f"{'scenario (question)':<46} {'runs':>5} {'clean':>6} {'off':>5} {'rate':>7}")
    print("-" * 74)
    worst = 0.0
    for question, tally in sorted(by_scenario.items()):
        runs = sum(tally.values())
        clean = tally.get("ok", 0)
        off = runs - clean
        rate = off / runs if runs else 0.0
        worst = max(worst, rate)
        print(f"{question:<46} {runs:>5} {clean:>6} {off:>5} {rate * 100:>6.1f}%")

    print("\nby signal:")
    signals = collections.Counter(
        v for t in by_scenario.values() for v, n in t.items() for _ in range(n)
    )
    for name, count in signals.most_common():
        print(f"  {name:<16} {count}")

    # A scenario that never behaves has no baseline, which is the flaw this corpus exists to avoid.
    if worst >= 0.95:
        print(
            "\nFAIL: a scenario is wrong on every run — no baseline for a detector", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
