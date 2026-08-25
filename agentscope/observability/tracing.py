from __future__ import annotations

from contextlib import nullcontext
from typing import Any


def span(name: str, **attributes: str) -> Any:
    """Return an OpenTelemetry span when the SDK is configured, otherwise a no-op context."""
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("agentscope")
        return tracer.start_as_current_span(name, attributes=attributes)
    except ImportError:
        return nullcontext()
