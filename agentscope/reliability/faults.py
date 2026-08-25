from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from agentscope.agents.base import AgentEnvironment
from agentscope.domain.models import FaultInjectionPolicy
from agentscope.execution.tools.models import ToolDefinition, ToolOutput


class FaultInjectingEnvironment:
    """Seeded per-run fault stream, making tool fault decisions replayable."""

    def __init__(self, wrapped: AgentEnvironment, policy: FaultInjectionPolicy) -> None:
        self.wrapped = wrapped
        self.policy = policy
        self._random = random.Random(policy.seed)
        self._lock = asyncio.Lock()

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        return self.wrapped.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        started = time.monotonic()
        async with self._lock:
            failure_roll = self._random.random()
            timeout_roll = self._random.random()
        if self.policy.additional_tool_latency_ms:
            await asyncio.sleep(self.policy.additional_tool_latency_ms / 1000)
        elapsed = (time.monotonic() - started) * 1000
        if timeout_roll < self.policy.tool_timeout_probability:
            return ToolOutput(False, "", elapsed, "injected tool timeout", {"injected": True})
        if failure_roll < self.policy.tool_failure_probability:
            return ToolOutput(False, "", elapsed, "injected tool failure", {"injected": True})
        return await self.wrapped.call_tool(name, arguments)

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
        await self.wrapped.record_model_call(
            model,
            duration_ms,
            input_tokens,
            output_tokens,
            status=status,
            error=error,
        )
