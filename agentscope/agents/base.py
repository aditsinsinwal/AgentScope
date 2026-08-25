from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agentscope.domain.models import EvaluationTask
from agentscope.execution.tools.models import ToolDefinition, ToolOutput
from agentscope.execution.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class Usage:
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass(frozen=True, slots=True)
class AgentResult:
    completed: bool
    message: str
    steps: int
    tool_calls: int
    usage: Usage = field(default_factory=Usage)


class AgentEnvironment(Protocol):
    @property
    def tools(self) -> tuple[ToolDefinition, ...]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutput: ...

    async def record_model_call(
        self,
        model: str,
        duration_ms: float,
        input_tokens: int,
        output_tokens: int,
        *,
        status: str = "success",
        error: str | None = None,
    ) -> None: ...


class Agent(Protocol):
    async def run(self, task: EvaluationTask, environment: AgentEnvironment) -> AgentResult: ...


class ToolEnvironment:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._registry.definitions)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        return await self._registry.call(name, arguments)

    async def record_model_call(
        self,
        model: str,
        duration_ms: float,
        input_tokens: int,
        output_tokens: int,
        *,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        from agentscope.tracing.models import EventType, TraceEvent

        await self._registry.recorder.append(
            TraceEvent(
                self._registry.run_id,
                0,
                EventType.MODEL_CALL,
                "chat_completion",
                duration_ms=duration_ms,
                status=status,
                error=error,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )
