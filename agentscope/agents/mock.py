from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from agentscope.agents.base import AgentEnvironment, AgentResult
from agentscope.domain.models import EvaluationTask


@dataclass(frozen=True, slots=True)
class MockAction:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


class MockAgent:
    """Deterministic scripted agent; no model API or hidden-test access."""

    def __init__(self, actions: Sequence[MockAction], *, stop_on_error: bool = True) -> None:
        self.actions = tuple(actions)
        self.stop_on_error = stop_on_error

    async def run(self, task: EvaluationTask, environment: AgentEnvironment) -> AgentResult:
        del task
        completed = True
        messages: list[str] = []
        calls = 0
        for action in self.actions:
            output = await environment.call_tool(action.tool, action.arguments)
            calls += 1
            if not output.success:
                messages.append(f"{action.tool}: {output.error}")
                if self.stop_on_error:
                    completed = False
                    break
        return AgentResult(completed, "; ".join(messages) or "script complete", calls, calls)
