from pathlib import Path
from typing import Any

import httpx

from agentscope.agents.providers.openai_compatible import OpenAICompatibleAgent
from agentscope.domain.models import (
    AgentConfiguration,
    EvaluationTask,
    ModelConfiguration,
    TaskId,
)
from agentscope.execution.tools.models import ToolDefinition, ToolOutput


class RecordingEnvironment:
    tools: tuple[ToolDefinition, ...] = ()

    def __init__(self) -> None:
        self.model_events: list[tuple[str, int, int]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        raise AssertionError("no tool call expected")

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
        assert duration_ms >= 0
        assert status == "success" and error is None
        self.model_events.append((model, input_tokens, output_tokens))


async def test_openai_compatible_adapter_records_factual_usage(tmp_path: Path) -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "done"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        )

    configuration = AgentConfiguration(
        "compatible",
        ModelConfiguration("compatible", "test-model", "https://provider.invalid/v1"),
    )
    task = EvaluationTask(
        TaskId("task"),
        "Task",
        tmp_path,
        "Do it",
        ("pytest",),
        ("pytest",),
    )
    environment = RecordingEnvironment()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await OpenAICompatibleAgent(configuration, "secret", client=client).run(
            task, environment
        )
    assert result.completed
    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 3
    assert environment.model_events == [("test-model", 11, 3)]
