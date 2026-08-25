from __future__ import annotations

import json
import time
from typing import Any

import httpx

from agentscope.agents.base import AgentEnvironment, AgentResult, Usage
from agentscope.domain.errors import AgentExecutionError
from agentscope.domain.models import AgentConfiguration, EvaluationTask


class OpenAICompatibleAgent:
    """Minimal OpenAI-compatible chat/tool loop with configurable endpoint.

    Credentials stay in this host-side adapter and are never passed to the sandbox.
    """

    def __init__(
        self,
        configuration: AgentConfiguration,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if configuration.model is None:
            raise ValueError("a model configuration is required")
        self.configuration = configuration
        self.api_key = api_key
        self._client = client

    async def run(self, task: EvaluationTask, environment: AgentEnvironment) -> AgentResult:
        model = self.configuration.model
        assert model is not None
        endpoint = (model.base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self.configuration.system_prompt
                or "Solve the task using only the provided tools. Never modify tests.",
            },
            {"role": "user", "content": task.description},
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in environment.tools
        ]
        usage = Usage()
        client = self._client or httpx.AsyncClient(timeout=60)
        owns_client = self._client is None
        tool_calls = 0
        try:
            for step in range(1, self.configuration.max_steps + 1):
                started = time.monotonic()
                response = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": model.model,
                        "messages": messages,
                        "tools": tools,
                        "temperature": model.temperature,
                        "max_tokens": model.max_output_tokens,
                    },
                )
                if response.status_code == 429:
                    raise AgentExecutionError("model provider rate limited the run")
                response.raise_for_status()
                payload = response.json()
                token_data = payload.get("usage", {})
                call_input_tokens = int(token_data.get("prompt_tokens", 0))
                call_output_tokens = int(token_data.get("completion_tokens", 0))
                await environment.record_model_call(
                    model.model,
                    (time.monotonic() - started) * 1000,
                    call_input_tokens,
                    call_output_tokens,
                )
                usage = Usage(
                    usage.model_calls + 1,
                    usage.input_tokens + call_input_tokens,
                    usage.output_tokens + call_output_tokens,
                    usage.cached_tokens + int(token_data.get("cached_tokens", 0)),
                )
                message = payload["choices"][0]["message"]
                messages.append(message)
                requested = message.get("tool_calls", [])
                if not requested:
                    return AgentResult(
                        True, message.get("content") or "finished", step, tool_calls, usage
                    )
                for call in requested:
                    function = call["function"]
                    try:
                        arguments = json.loads(function["arguments"])
                    except json.JSONDecodeError:
                        arguments = {}
                    result = await environment.call_tool(function["name"], arguments)
                    tool_calls += 1
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": result.content
                            if result.success
                            else f"ERROR: {result.error}",
                        }
                    )
            raise AgentExecutionError(f"agent exceeded {self.configuration.max_steps} steps")
        finally:
            if owns_client:
                await client.aclose()
