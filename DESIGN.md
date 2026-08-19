# support-desk-agent — a corpus built for the detectors that exist

The previous test bed measured the wrong thing. Its defects were deterministic: the same
question produced the same wrong answer every time, so within any group of similar requests
being wrong *was* the norm. There was no anomaly to find, and a detector that looks for one
found nothing. That result was real, but it graded the corpus, not the product.

This one is built the other way round. Every defect is chosen because MEGA Loop's own
description says it can be detected, and each is triggered so the signal it needs is present.

## The two rules that shape everything

**A defect that always fires is invisible to a detector that looks for outliers.** So the
trigger is something the question does not contain — the ticket id. The same words go in; the
outcome differs.

    always-wrong   ✗✗✗✗✗✗✗✗✗✗    nothing stands out
    intermittent   ✓✓✓✓✓✓✓✓✓✗    the ✗ is the finding

**A scenario carries at most one defect.** This is the rule the first build of this corpus
missed, and the arithmetic is unforgiving: fourteen defects each firing independently at 10%
leaves 0.9^14 — about a quarter — of runs clean. Every individual rate looked right and the
corpus was still wrong more often than not.

Ownership moves the rate from per-defect to per-group. A scenario is what a detector clusters,
so a scenario is where the 90/10 has to hold, and each one has exactly one thing that can go
wrong with it. Measured over 1 700 tickets, every scenario lands between 6% and 14%.

## Coverage

Each row is one scenario family, mapped to the failure it is meant to produce.

**Twelve defects are scored.** Five more are planted and deliberately excluded — see *Out of
scope* below. The denominator is what MEGA Loop can detect today, not what we found interesting
to break. Scoring a product against a claim it never made is what made the previous test bed
unreadable.

### Error failures — explicitly broken

| id | Produces | How | Rate |
|---|---|---|---|
| `E1` | tool execution failure | `order_lookup` raises on orders whose id hashes into a bad shard | ~10% |
| `E2` | internal step failure | refund maths raises on a legacy record with no currency | ~10% |
| `E3` | agent convergence failure | planner loops on an ambiguous ask, gives up, raises | ~10% |
| `E4` | hallucinated tool call | model calls `escalate_ticket`, which was never declared | ~10% |
| `E5` | invalid tool arguments | required `order_id` missing from the call it makes | ~10% |

### Silent failures — look successful, are not

| id | Produces | How | Rate |
|---|---|---|---|
| `S1` | empty final response | model returns "" and the app passes it through | ~10% |
| `S3` | high latency | a retry sleep fires on a subset | ~10% |
| `S4` | oversized tool output | catalogue dump floods the context | ~10% |
| `S5` | error hidden in response | body reads "Error: could not reach billing", status OK | ~10% |
| `S6` | unsupported confident answer | retriever returns nothing, answer is stated as fact | ~10% |

### Quality failures — judged against the request

| id | Produces | How | Rate |
|---|---|---|---|
| `Q1` | instruction not followed | asked for two sentences, returns six | ~10% |
| `Q2` | not grounded | quotes a refund window no retrieved document states | ~10% |

### Out of scope — MEGA Loop cannot detect these today

Five defects stay in the code and still fire, and none of them is **scored**. Two have no
detector at all; three depend on judge axes that are shipped but disabled behind a flag.

**No detector exists**

| id | Produces | Why it cannot be found |
|---|---|---|
| `E6` | output schema violation | `observe_conformance` ends `# output-schema conformance: no declared_output_schema in mega-loop -> emit nothing`. Nothing reads the `output.schema` attribute the reply carries. |
| `S2` | missing token accounting | `zero_usage_spans` is imported only by `readiness.py`. It grades trace quality and never files a failure, so no instrumentation makes it a bug. |

**Judge axis behind a flag**

`answer_completion`, `relevance` and `toxicity` have finished rubrics in `JUDGE_TEMPLATES`, and
`COMING_SOON_AXES` holds all three. The comment above that set reads *"Axes still behind a flag
— PUT rejects enabling them"*, and `PUT /v1/settings/judge-axes` answers
`422 axis_not_available`. Verified live, not inferred.

| id | Needs axis | Status |
|---|---|---|
| `Q3` | `answer_completion` | coming soon — cannot be enabled |
| `Q4` | `relevance` | coming soon — cannot be enabled |
| `Q5` | `toxicity` | coming soon — cannot be enabled |

These five are worth keeping in the corpus rather than deleting: the day an axis ships or a
detector lands, the traffic that exercises it already exists. Their scenarios are neither scored
defects nor controls — something is wrong in them and nothing should report it, which is correct
behaviour rather than a miss.

### Control

| id | Produces |
|---|---|
| `C1`–`C4` | nothing. Correct, grounded, complete, on topic, every run. |

### On the safety case

`Q5` exercises the harmfulness check without writing anything harmful to read. The unsafe act is
a **disclosure**: a truncated id joins the wrong customer record, so the reply hands one person
another person's email and phone number. Every value is synthetic and obviously so, and the
failure is a real one — a wrong join leaking PII is how this goes wrong in production, far more
often than a model saying something offensive.

Violent or self-harm content is still out. A detector for that is worth having; a corpus
carrying examples of it is not, and the same detector fires on a disclosure.

## The shape each detector actually reads

Dry-running MEGA Loop's own detectors over locally captured spans — the LLM stubbed, Langfuse out
of the path — found five places where a defect existed, was correct in spirit, and produced
nothing. Each is recorded because none of them is guessable from the failure description alone.

**An empty result has to read as empty.** `_empty_output` measures the output *string*.
`kb_search` used to write `{"count": 0, "ids": []}`, a perfectly non-empty string, so a retrieval
that found nothing was scored as a span with output. It now writes no output value at all when it
finds nothing, and `empty_result` plus `empty_evidence` both fire.

**A confident answer must not decline.** `observe_empty_evidence` also requires the final answer
to be substantive and free of decline language. The standing system prompt tells the model to say
so when the extracts do not cover the question — an admission the detector correctly reads as the
model behaving well. On an S6 run that permission is removed, or the defect defeats itself.

**Every question has to reach an article.** Four scenarios asked things no `_TOPIC` keyword
matched, so `kb_search` was empty on 100% of their runs — including one control, which would have
produced a guaranteed false positive. Routing was added for `status`, `order`, `escalat`, `damage`
and `wrap`, and a `KB-ESCALATION` article now exists.

**A defect needs a signature of its own.** E5 raised in the body of `ask`, so the only errored
span was the root AGENT — whose signature `tool_loop:support_desk.ask` every uncaught exception in
this app already produces. Its failures landed in E3's issue and the analyst saw two mechanisms as
one. The rejected call now errors inside a `tool_dispatch` span of its own.

**A slow span must stay rare enough to look slow.** The latency line is
`max(p95 * 3, 10.0)` over the span name's own history, needing 30+ samples. Two consequences: a
3-second sleep can never cross the ten-second floor, so the sleep is 12s; and the p95 is computed
over a population that *includes* the defect, so if the slow share of `shipping_estimate` rose
above 5% the p95 would land inside the slow band and the line would jump to 36s — the defect would
hide itself. Measured: 11 slow of 400, or 2.8%.

## What each defect must NOT do

Fire on every run of its scenario. If it did, this corpus would have the same flaw as the last
one. The rate above is the design, and `verify_rates.py` asserts them against the traces that
actually landed.
