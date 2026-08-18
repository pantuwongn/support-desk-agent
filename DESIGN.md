# support-desk-agent — a corpus built for the detectors that exist

The previous test bed measured the wrong thing. Its defects were deterministic: the same
question produced the same wrong answer every time, so within any group of similar requests
being wrong *was* the norm. There was no anomaly to find, and a detector that looks for one
found nothing. That result was real, but it graded the corpus, not the product.

This one is built the other way round. Every defect is chosen because MEGA Loop's own
description says it can be detected, and each is triggered so the signal it needs is present.

## The rule that shapes everything

**A defect that always fires is invisible to a detector that looks for outliers.**

So the intermittent ones key off something the question does not contain — a customer id, a
shard, an order age. The same words go in; the outcome differs. That is the pattern:

    always-wrong   ✗✗✗✗✗✗✗✗✗✗    nothing stands out
    intermittent   ✓✓✓✗✓✓✓✓✗✓    the ✗ is the finding

## Coverage

Each row is one scenario family, mapped to the failure it is meant to produce.

### Error failures — explicitly broken

| id | Produces | How | Rate |
|---|---|---|---|
| `E1` | tool execution failure | `order_lookup` raises on orders whose id hashes into a bad shard | ~10% |
| `E2` | internal step failure | refund maths raises on a legacy record with no currency | ~10% |
| `E3` | agent convergence failure | planner loops on an ambiguous ask, gives up, raises | ~10% |
| `E4` | hallucinated tool call | model calls `escalate_ticket`, which was never declared | ~10% |
| `E5` | invalid tool arguments | required `order_id` missing from the call it makes | ~10% |
| `E6` | output schema violation | reply drops the `ticket_id` the downstream needs | ~10% |

### Silent failures — look successful, are not

| id | Produces | How | Rate |
|---|---|---|---|
| `S1` | empty final response | model returns "" and the app passes it through | ~10% |
| `S2` | missing token accounting | usage recorded as 0 on one code path | ~10% |
| `S3` | high latency | a retry sleep fires on a subset | ~10% |
| `S4` | oversized tool output | catalogue dump floods the context | ~10% |
| `S5` | error hidden in response | body reads "Error: could not reach billing", status OK | ~10% |
| `S6` | unsupported confident answer | retriever returns nothing, answer is stated as fact | ~10% |

### Quality failures — judged against the request

| id | Produces | How | Rate |
|---|---|---|---|
| `Q1` | instruction not followed | asked for two sentences, returns six | ~10% |
| `Q2` | not grounded | quotes a refund window no retrieved document states | ~10% |
| `Q3` | incomplete | two-part question, one part answered | ~10% |
| `Q4` | irrelevant | answers shipping when asked about billing | ~10% |
| `Q5` | unsafe output | the reply carries another customer's contact details | ~10% |

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

## What each defect must NOT do

Fire on every run of its scenario. If it did, this corpus would have the same flaw as the last
one. The rate above is the design, and `verify_rates.py` asserts them against the traces that
actually landed.
