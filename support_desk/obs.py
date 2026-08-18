"""OpenTelemetry setup and span helpers, written to the OpenInference contract.

Every span declares an `openinference.span.kind`; the kind is an argument rather than something
a call site can forget. Export target comes from the environment — `LANGFUSE_*` for Langfuse
over OTLP HTTP, `OTEL_EXPORTER_OTLP_ENDPOINT` for a gRPC collector, neither for tracing off.
"""

from __future__ import annotations

import base64
import json
import os
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

OI_KIND = "openinference.span.kind"
_TRACER = "support_desk"
_initialized = False


def _exporter() -> object | None:
    host = os.environ.get("LANGFUSE_HOST", "").strip().rstrip("/")
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if host and public and secret:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HttpExporter,
        )

        token = base64.b64encode(f"{public}:{secret}".encode()).decode()
        return HttpExporter(
            endpoint=f"{host}/api/public/otel/v1/traces",
            headers={"Authorization": f"Basic {token}"},
        )
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return None
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter as GrpcExporter,
    )

    return GrpcExporter(endpoint=endpoint, insecure=not endpoint.startswith("https://"))


def setup_tracing() -> bool:
    global _initialized
    if _initialized:
        return True
    exporter = _exporter()
    if exporter is None:
        return False
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    project = os.environ.get("OTEL_PROJECT_NAME", "support-desk")
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": "support-desk", "openinference.project.name": project}
        )
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _initialized = True
    return True


def shutdown() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "shutdown"):
        provider.shutdown()


def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


@contextmanager
def span(name: str, kind: str, **attributes: Any):
    tracer = trace.get_tracer(_TRACER)
    attrs = {OI_KIND: kind}
    attrs.update({k: as_text(v) for k, v in attributes.items() if v is not None})
    with tracer.start_as_current_span(name, attributes=attrs) as sp:
        try:
            yield sp
        except Exception as exc:
            sp.set_status(Status(StatusCode.ERROR, str(exc)))
            sp.set_attribute("status_message", f"{type(exc).__name__}: {exc}")
            raise


def set_output(sp: Any, value: Any) -> None:
    sp.set_attribute("output.value", as_text(value))


def set_documents(sp: Any, documents: list[dict[str, Any]]) -> None:
    for i, doc in enumerate(documents):
        base = f"retrieval.documents.{i}.document"
        sp.set_attribute(f"{base}.id", str(doc.get("id", "")))
        sp.set_attribute(f"{base}.content", as_text(doc.get("content", "")))


def set_messages(sp: Any, prefix: str, messages: list[dict[str, str]]) -> None:
    for i, message in enumerate(messages):
        sp.set_attribute(f"{prefix}.{i}.message.role", message.get("role", "user"))
        sp.set_attribute(f"{prefix}.{i}.message.content", as_text(message.get("content", "")))


def declare_tools(sp: Any, tools: list[dict[str, Any]]) -> None:
    """Stamp the tools the model was offered, so a call to anything else is visibly invented."""
    for i, tool in enumerate(tools):
        sp.set_attribute(f"llm.tools.{i}.tool.json_schema", as_text(tool))


def record_tool_calls(sp: Any, calls: list[tuple[str, dict[str, Any]]]) -> None:
    """Record the calls the model asked for, on the LLM span that asked for them.

    A reader answers "did it call something that was never offered" by comparing these against
    `llm.tools.*`, so both have to sit on the same span in the layout it expects. Opening a
    child span named after the tool is not the same claim: that says the call happened, not
    that the model chose it, and nothing can tell an invented name from a real one.
    """
    for i, (name, arguments) in enumerate(calls):
        base = f"llm.output_messages.0.message.tool_calls.{i}.tool_call.function"
        sp.set_attribute(f"{base}.name", name)
        sp.set_attribute(f"{base}.arguments", as_text(arguments))
