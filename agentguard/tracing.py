import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_telemetry():
    provider = TracerProvider(resource=Resource.create({"service.name": "agentguard"}))
    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider


def now():
    return datetime.now(UTC).isoformat()


class RunTrace:
    def __init__(self, run_id):
        self.run_id = run_id
        self.spans = []
        self.stack = []

    @contextmanager
    def span(self, name, **attributes):
        span = {
            "id": uuid4().hex[:16],
            "parent_id": self.stack[-1] if self.stack else None,
            "name": name,
            "started_at": now(),
            "attributes": attributes,
            "status": "ok",
        }
        self.spans.append(span)
        self.stack.append(span["id"])
        start = time.perf_counter()
        # Payloads stay local. Export only metadata to avoid leaking prompts by default.
        with trace.get_tracer("agentguard").start_as_current_span(
            name, record_exception=False, set_status_on_exception=False
        ) as otel:
            context = otel.get_span_context()
            span["otel_trace_id"] = f"{context.trace_id:032x}"
            otel.set_attribute("agentguard.run_id", self.run_id)
            try:
                yield span["attributes"]
            except Exception as exc:
                span["status"] = "error"
                span["error"] = type(exc).__name__
                otel.set_status(trace.Status(trace.StatusCode.ERROR, type(exc).__name__))
                raise
            finally:
                span["latency_ms"] = round((time.perf_counter() - start) * 1000, 3)
                otel.set_attribute("agentguard.status", span["status"])
                for key in ("agent_id", "model", "provider", "input_tokens", "output_tokens", "cost", "step"):
                    value = span["attributes"].get(key)
                    if isinstance(value, (str, int, float, bool)):
                        otel.set_attribute("agentguard." + key, value)
                self.stack.pop()
