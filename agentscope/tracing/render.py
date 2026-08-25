from collections.abc import Sequence

from agentscope.tracing.models import TraceEvent


def render_trace(events: Sequence[TraceEvent], from_step: int = 1) -> str:
    lines: list[str] = []
    for event in events:
        if event.sequence < from_step:
            continue
        duration = "" if event.duration_ms is None else f" ({event.duration_ms:.1f}ms)"
        lines.append(
            f"{event.sequence:04d} {event.timestamp.isoformat()} "
            f"{event.event_type.value}:{event.name} [{event.status}]{duration}"
        )
        if event.input_summary:
            lines.append(f"     input: {event.input_summary}")
        if event.output_summary:
            lines.append(f"     output: {event.output_summary}")
        if event.error:
            lines.append(f"     error: {event.error}")
    return "\n".join(lines)
