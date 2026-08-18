"""Run the desk: one ticket, or a batch that produces a corpus worth grading."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from support_desk import agent, generate, obs


def _run_one(case: dict[str, Any]) -> dict[str, Any]:
    try:
        result = agent.ask(
            case["question"],
            ticket_id=case["ticket_id"],
            customer_id=case.get("customer_id", "CUST-1001"),
        )
        return {"id": case["id"], "ok": True, **result}
    except Exception as exc:  # noqa: BLE001 — one bad ticket must not stop the batch
        return {"id": case["id"], "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="support-desk")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--ticket-id", default="T-000001")
    parser.add_argument("--traffic", type=int, help="run N tickets drawn from the scenarios")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    traced = obs.setup_tracing()
    print(f"tracing: {'on' if traced else 'off'}", file=sys.stderr)
    try:
        if args.question:
            result = _run_one(
                {"id": "adhoc", "question": args.question, "ticket_id": args.ticket_id}
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1

        runs = generate.plan(args.traffic or 14, seed=args.seed)
        raised = 0
        for position, case in enumerate(runs, start=1):
            raised += not _run_one(case)["ok"]
            if position % 25 == 0 or position == len(runs):
                print(f"  {position}/{len(runs)}", file=sys.stderr)
        print(f"\n{len(runs)} tickets, {raised} raised", file=sys.stderr)
        return 0
    finally:
        obs.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
