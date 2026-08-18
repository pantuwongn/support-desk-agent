"""The model call, recorded as an LLM span with prompt, answer and token counts."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from support_desk import faults, obs

DEFAULT_MODEL = os.environ.get("SUPPORT_DESK_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = (
    "You are a customer support desk. Answer only from the knowledge-base extracts and tool "
    "results you are given. Cite the article id you used. If the extracts do not cover the "
    "question, say so. Answer in two sentences or fewer."
)


class LlmError(RuntimeError):
    """The model could not be reached or returned nothing usable."""


@lru_cache(maxsize=1)
def _client() -> Any:
    from google import genai

    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise LlmError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=key)


def answer(
    question: str,
    facts: list[str],
    *,
    ticket_id: str,
    scenario: str = "",
    model: str = DEFAULT_MODEL,
) -> str:
    """Draft the reply.

    S1: on ~10% of tickets the model's text is dropped and the empty string is passed through.
    S2: on ~10% the usage block is not read, so the span reports no tokens at all.
    Q1: on ~10% the two-sentence instruction is removed from the prompt, and the reply runs long.
    """
    context = "\n\n".join(f"[{i + 1}] {text}" for i, text in enumerate(facts))
    system = SYSTEM_PROMPT
    if faults.fires(ticket_id, "Q1", scenario=scenario):
        system = system.replace(" Answer in two sentences or fewer.", "") + (
            " Explain the reasoning behind the policy in full, with examples."
        )
    user = f"Knowledge base:\n{context}\n\nCustomer question: {question}"
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    with obs.span("draft_reply", "LLM", **{"input.value": user}) as sp:
        sp.set_attribute("llm.model_name", model)
        sp.set_attribute("llm.provider", "google")
        obs.set_messages(sp, "llm.input_messages", messages)
        obs.declare_tools(sp, __import__("support_desk.tools", fromlist=["DECLARED"]).DECLARED)

        response = _client().models.generate_content(
            model=model,
            contents=user,
            config={"system_instruction": system, "temperature": 0.0},
        )
        text = (response.text or "").strip()
        if faults.fires(ticket_id, "S1", scenario=scenario):
            text = ""

        if not faults.fires(ticket_id, "S2", scenario=scenario):
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                prompt_tokens = getattr(usage, "prompt_token_count", None)
                completion_tokens = getattr(usage, "candidates_token_count", None)
                if prompt_tokens is not None:
                    sp.set_attribute("llm.token_count.prompt", int(prompt_tokens))
                if completion_tokens is not None:
                    sp.set_attribute("llm.token_count.completion", int(completion_tokens))
                if prompt_tokens is not None and completion_tokens is not None:
                    sp.set_attribute(
                        "llm.token_count.total", int(prompt_tokens) + int(completion_tokens)
                    )

        obs.set_messages(sp, "llm.output_messages", [{"role": "assistant", "content": text}])
        obs.set_output(sp, text)
        return text
