"""The support desk: a ticket in, a reply out, traced end to end."""

from __future__ import annotations

import re
from typing import Any

from support_desk import faults, llm, obs, retrieve, tools

_ORDER = re.compile(r"\bORD-\d{5}\b")
_CUSTOMER = re.compile(r"\bCUST-\d{4}\b")

#: What the downstream ticketing system requires of every reply.
REPLY_SCHEMA = ("ticket_id", "reply", "citations")


class ConvergenceFailure(RuntimeError):
    """The planner could not settle on a course of action."""


def _plan(question: str, *, ticket_id: str) -> list[str]:
    """Decide which tools to run. A CHAIN — it chooses, it does not compute.

    E3: on ~10% of tickets an ambiguous ask sends the planner round the same three steps until
    it gives up. Recorded as the loop it was, then raised.
    """
    with obs.span("plan", "CHAIN", **{"input.value": question}) as sp:
        lowered = question.lower()
        steps: list[str] = []
        if _ORDER.search(question):
            steps.append("order_lookup")
        if "refund" in lowered or "money back" in lowered:
            steps.append("refund_quote")
        if "ship" in lowered or "deliver" in lowered or "arrive" in lowered:
            steps.append("shipping_estimate")
        if _CUSTOMER.search(question) or "account" in lowered or "seat" in lowered:
            steps.append("account_summary")

        if faults.fires(ticket_id, "E3"):
            sp.set_attribute("planner.iterations", 8)
            sp.set_attribute("planner.repeated_steps", obs.as_text(steps * 3))
            raise ConvergenceFailure(
                "planner revisited the same 3 steps 8 times without settling on an action"
            )

        obs.set_output(sp, steps)
        return steps


def _run_tool(name: str, arguments: dict[str, Any], *, ticket_id: str) -> dict[str, Any]:
    """Invoke one tool by name, with the arguments the planner chose."""
    fn = {
        "order_lookup": tools.order_lookup,
        "refund_quote": tools.refund_quote,
        "shipping_estimate": tools.shipping_estimate,
        "account_summary": tools.account_summary,
    }[name]
    return fn(**arguments, ticket_id=ticket_id)


def ask(question: str, *, ticket_id: str, customer_id: str = "CUST-1001") -> dict[str, Any]:
    """Answer one ticket."""
    with obs.span(
        "support_desk.ask",
        "AGENT",
        **{"input.value": {"question": question, "ticket_id": ticket_id}},
    ) as root:
        root.set_attribute("ticket.id", ticket_id)
        root.set_attribute("user.id", customer_id)

        steps = _plan(question, ticket_id=ticket_id)
        order_match = _ORDER.search(question)
        order_id = order_match.group(0) if order_match else "ORD-77001"

        facts: list[str] = []
        for step in steps:
            if step == "account_summary":
                arguments: dict[str, Any] = {"customer_id": customer_id}
            elif faults.fires(ticket_id, "E5"):
                # E5: the required order_id never makes it into the call.
                arguments = {}
            else:
                arguments = {"order_id": order_id}
            try:
                facts.append(
                    f"{step}: {obs.as_text(_run_tool(step, arguments, ticket_id=ticket_id))}"
                )
            except TypeError as exc:  # a call that violates the declared schema
                raise ValueError(f"{step} called without its required argument: {exc}") from exc

        # E4: a tool nobody declared. The span names it, so the call is visible as invented.
        if faults.fires(ticket_id, "E4"):
            with obs.span(
                "escalate_ticket", "TOOL", **{"input.value": {"ticket_id": ticket_id}}
            ) as sp:
                sp.set_attribute("tool.name", "escalate_ticket")
                obs.set_output(sp, {"escalated": True, "queue": "tier-2"})
            facts.append("escalate_ticket: {'escalated': True}")

        documents = retrieve.search(question, ticket_id=ticket_id)
        extracts = [f"{d['title']} §{d['section']}: {d['content']}" for d in documents]

        text = llm.answer(question, extracts + facts, ticket_id=ticket_id)

        # S5: the failure is written into the body while the status stays OK.
        if faults.fires(ticket_id, "S5"):
            text = "Error: could not reach the billing service. Please try again later."

        result: dict[str, Any] = {
            "ticket_id": ticket_id,
            "reply": text,
            "citations": [d["id"] for d in documents],
        }
        # E6: the key the downstream requires is dropped.
        if faults.fires(ticket_id, "E6"):
            result.pop("ticket_id")

        obs.set_output(root, result)
        return result
