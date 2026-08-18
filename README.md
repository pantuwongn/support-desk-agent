# support-desk-agent

A customer support desk with **seventeen planted defects**, built to test whether a trace-based
detector can find them.

Every defect fires on roughly **one ticket in ten**, and the trigger is the ticket id — a value
the question never contains. Ask the same question twice and it can succeed once and fail once.
That is deliberate: a defect that fires every time is the norm inside its own group, and a
detector looking for an outlier has nothing to find.

`DESIGN.md` lists every defect, what failure it is meant to produce, and why.

## Run it

```bash
uv sync
export GEMINI_API_KEY=...
uv run support-desk --traffic 600 --seed 1
```

Traces go wherever the environment points:

```bash
LANGFUSE_HOST=...  LANGFUSE_PUBLIC_KEY=...  LANGFUSE_SECRET_KEY=...   # Langfuse
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317                     # any collector
```

Neither set means tracing is off and the app behaves identically.

## What is deliberately wrong

Do not fix anything here. The defects are the fixture.
