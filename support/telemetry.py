"""Tracing (Stage 5): every turn becomes one trace in Phoenix (O-1 to O-4).

set_up() must run BEFORE any agent is built, so ADK's own spans (invoke_agent, call_llm,
execute_tool) and the Gemini spans land in the same trace as our agent.turn span.

Julia's decision: record everything, except card numbers, which are removed from every span
before it leaves this process.
"""

import atexit
import json
import re
import urllib.request

from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

PHOENIX = "http://localhost:6006"
PROJECT = "customer-support"

# 13 to 19 digits, optionally split by spaces or dashes: the shape of a payment card number.
CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _scrub(value):
    if isinstance(value, str):
        return CARD.sub("[card number removed]", value)
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub(v) for v in value)
    return value


class CardScrubbingExporter(SpanExporter):
    """Passes spans on to Phoenix with every card number in their attributes removed."""

    def __init__(self, inner: SpanExporter):
        self._inner = inner

    def export(self, spans):
        clean = [
            ReadableSpan(
                name=s.name, context=s.context, parent=s.parent, resource=s.resource,
                attributes={k: _scrub(v) for k, v in (s.attributes or {}).items()},
                events=s.events, links=s.links, kind=s.kind, status=s.status,
                start_time=s.start_time, end_time=s.end_time,
                instrumentation_scope=s.instrumentation_scope,
            )
            for s in spans
        ]
        return self._inner.export(clean)

    def shutdown(self):
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


_project_id: str | None = None


def set_up() -> trace.Tracer:
    """Global tracer provider (set once) plus Gemini auto-instrumentation (O-3)."""
    provider = TracerProvider(resource=Resource({"openinference.project.name": PROJECT}))
    exporter = CardScrubbingExporter(OTLPSpanExporter(endpoint=f"{PHOENIX}/v1/traces"))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    GoogleGenAIInstrumentor().instrument(tracer_provider=provider)
    atexit.register(provider.shutdown)  # send the last spans before the program ends
    return trace.get_tracer("support.pipeline")


def trace_url(trace_id: str) -> str:
    """A link that opens this trace in Phoenix (O-4)."""
    global _project_id
    if _project_id is None:
        with urllib.request.urlopen(f"{PHOENIX}/v1/projects") as r:
            projects = {p["name"]: p["id"] for p in json.load(r)["data"]}
        if PROJECT not in projects:
            req = urllib.request.Request(
                f"{PHOENIX}/v1/projects", data=json.dumps({"name": PROJECT}).encode(),
                headers={"content-type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req) as r:
                projects[PROJECT] = json.load(r)["data"]["id"]
        _project_id = projects[PROJECT]
    return f"{PHOENIX}/projects/{_project_id}/traces/{trace_id}"
