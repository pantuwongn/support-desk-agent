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


def _plan(
    question: str, *, ticket_id: str, scenario: str = "", customer_id: str = "", order_id: str = ""
) -> tuple[list[str], list[tuple[str, dict[str, Any]]]]:
    """Decide which tools to run. A CHAIN — it chooses, it does not compute.

    E3: on ~10% of tickets an ambiguous ask sends the planner round the same three steps until
    it gives up. Recorded as the loop it was, then raised.
    """
    with obs.span("plan", "LLM", **{"input.value": question}) as sp:
        obs.declare_tools(sp, tools.DECLARED)
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

        if faults.fires(ticket_id, "E3", scenario=scenario):
            sp.set_attribute("planner.iterations", 8)
            sp.set_attribute("planner.repeated_steps", obs.as_text(steps * 3))
            raise ConvergenceFailure(
                "planner revisited the same 3 steps 8 times without settling on an action"
            )

        # What the planner decided, in the layout a reader checks against `llm.tools.*`.
        # E4 adds a name that was never declared; E5 drops a required argument. Both are only
        # visible here — a child span named after the tool cannot show either.
        calls: list[tuple[str, dict[str, Any]]] = []
        for step in steps:
            if step == "account_summary":
                calls.append((step, {"customer_id": customer_id}))
            elif faults.fires(ticket_id, "E5", scenario=scenario):
                calls.append((step, {}))  # the required order_id never makes it in
            else:
                calls.append((step, {"order_id": order_id}))
        if faults.fires(ticket_id, "E4", scenario=scenario):
            calls.append(("escalate_ticket", {"ticket_id": ticket_id}))
        obs.record_tool_calls(sp, calls)
        obs.set_output(sp, steps)
        return steps, calls


#: The tools this desk can actually run. A name outside it was invented by the planner.
_TOOLS = {
    "order_lookup": tools.order_lookup,
    "refund_quote": tools.refund_quote,
    "shipping_estimate": tools.shipping_estimate,
    "account_summary": tools.account_summary,
}


def _run_tool(
    name: str, arguments: dict[str, Any], *, ticket_id: str, scenario: str = ""
) -> dict[str, Any]:
    """Invoke one tool by name, with the arguments the planner chose."""
    return _TOOLS[name](**arguments, ticket_id=ticket_id, scenario=scenario)


def ask(
    question: str, *, ticket_id: str, scenario: str = "", customer_id: str = "CUST-1001"
) -> dict[str, Any]:
    """Answer one ticket."""
    with obs.span(
        "support_desk.ask",
        "AGENT",
        **{"input.value": {"question": question, "ticket_id": ticket_id}},
    ) as root:
        root.set_attribute("ticket.id", ticket_id)
        root.set_attribute("user.id", customer_id)
        root.set_attribute("mega.scenario", scenario)

        order_match = _ORDER.search(question)
        order_id = order_match.group(0) if order_match else "ORD-77001"
        _steps, calls = _plan(
            question,
            ticket_id=ticket_id,
            scenario=scenario,
            customer_id=customer_id,
            order_id=order_id,
        )

        facts: list[str] = []
        for name, arguments in calls:
            if name not in _TOOLS:
                continue  # the invented one — the planner asked, nothing runs
            try:
                ran = _run_tool(name, arguments, ticket_id=ticket_id, scenario=scenario)
            except TypeError as exc:
                # The rejected call gets a span of its own. Without one the only errored span
                # is the root AGENT, whose signature is `tool_loop:support_desk.ask` — which
                # every uncaught exception in this app already produces, so E5's failures
                # would land in E3's issue and the analyst would see two mechanisms as one.
                with obs.span(
                    "tool_dispatch",
                    "CHAIN",
                    **{"input.value": {"tool": name, "arguments": arguments}},
                ):
                    raise ValueError(
                        f"{name} called without its required argument: {exc}"
                    ) from exc
            facts.append(f"{name}: {obs.as_text(ran)}")

        documents = retrieve.search(question, ticket_id=ticket_id, scenario=scenario)
        extracts = [f"{d['title']} §{d['section']}: {d['content']}" for d in documents]

        text = llm.answer(question, extracts + facts, ticket_id=ticket_id, scenario=scenario)

        # S5: the failure is written into the body while the status stays OK. Recorded on a
        # CHAIN span whose output LEADS with the sentinel — a reader checks the first 120
        # characters, so an error buried inside a JSON envelope is invisible to it.
        if faults.fires(ticket_id, "S5", scenario=scenario):
            text = "Error: could not reach the billing service. Please try again later."
            with obs.span("compose_reply", "CHAIN", **{"input.value": question}) as sp:
                obs.set_output(sp, text)

        result: dict[str, Any] = {
            "ticket_id": ticket_id,
            "reply": text,
            "citations": [d["id"] for d in documents],
        }
        # E6: the key the downstream requires is dropped. The schema rides on the root so a
        # reader can see what the reply was supposed to contain.
        root.set_attribute("output.schema", obs.as_text({"required": list(REPLY_SCHEMA)}))
        if faults.fires(ticket_id, "E6", scenario=scenario):
            result.pop("ticket_id")

        # S1: when the reply is empty the root records nothing either. The detector reads the
        # LAST generative span, and kinds LLM and AGENT both count — this root is an AGENT and
        # ends after `draft_reply`, so an envelope populated around an empty reply hides the
        # blank answer behind a non-empty root and the trace reads as answered.
        obs.set_output(root, result if text else "")
        return result
