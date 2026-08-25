from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from agentscope.domain.models import RunId, utc_now


class EventType(StrEnum):
    RUN_STATE = "run_state"
    AGENT_STEP = "agent_step"
    MODEL_CALL = "model_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    EVALUATION = "evaluation"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TraceEvent:
    run_id: RunId
    sequence: int
    event_type: EventType
    name: str
    timestamp: datetime = field(default_factory=utc_now)
    duration_ms: float | None = None
    status: str = "success"
    input_summary: str | None = None
    output_summary: str | None = None
    error: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
