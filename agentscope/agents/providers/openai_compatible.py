from __future__ import annotations

import asyncio
import json
import random as _random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from agentscope.agents.base import AgentEnvironment, AgentResult, Usage
from agentscope.config import get_settings
from agentscope.domain.errors import AgentLimitExceeded, ProviderError, ToolExecutionError
from agentscope.domain.models import AgentConfiguration, EvaluationTask

Sleep = Callable[[float], Awaitable[None]]
Uniform = Callable[[float, float], float]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential backoff with full jitter."""

    max_attempts: int = 4
    base_seconds: float = 0.5
    cap_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_seconds < 0 or self.cap_seconds < 0:
            raise ValueError("backoff durations must not be negative")

    @classmethod
    def from_settings(cls) -> RetryPolicy:
        settings = get_settings()
        return cls(
            settings.provider_max_attempts,
            settings.provider_backoff_base_seconds,
            settings.provider_backoff_cap_seconds,
        )


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds form only; HTTP-date values are ignored in favour of computed backoff."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 and seconds == seconds and seconds != float("inf") else None


def _token(data: dict[str, Any], key: str) -> int | None:
    value = data.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class OpenAICompatibleAgent:
    """Minimal OpenAI-compatible chat/tool loop with configurable endpoint.

    Credentials stay in this host-side adapter and are never passed to the sandbox, never put in
    error messages and never recorded in traces.

    Failure model:
    * transport errors, 429 and 5xx are retried with capped exponential backoff and full jitter
      (``Retry-After`` seconds honoured, capped); other 4xx are never retried;
    * a malformed provider response is a non-retryable ``ProviderError`` (the run cannot continue
      without a coherent assistant message);
    * a malformed or unknown *tool call* is the model's mistake, so it is fed back to the model as
      a tool error and the loop continues; the step and tool-call caps bound how long that can go
      on, ending in ``AgentLimitExceeded``.
    """

    def __init__(
        self,
        configuration: AgentConfiguration,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        retry: RetryPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        uniform: Uniform = _random.uniform,
        max_tool_calls: int | None = None,
    ) -> None:
        if configuration.model is None:
            raise ValueError("a model configuration is required")
        self.configuration = configuration
        self.api_key = api_key
        self._client = client
        self.retry = retry or RetryPolicy.from_settings()
        self._sleep = sleep
        self._uniform = uniform
        self.max_tool_calls = max_tool_calls or get_settings().agent_max_tool_calls

    def _redact(self, text: str) -> str:
        return text.replace(self.api_key, "[redacted]") if self.api_key else text

    def _delay(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self.retry.cap_seconds)
        ceiling = min(self.retry.cap_seconds, self.retry.base_seconds * (2 ** (attempt - 1)))
        return self._uniform(0.0, ceiling)

    async def _post(
        self, client: httpx.AsyncClient, endpoint: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            attempt += 1
            retry_after: float | None = None
            try:
                response = await client.post(
                    endpoint, headers={"Authorization": f"Bearer {self.api_key}"}, json=body
                )
            except httpx.TransportError as exc:
                error = ProviderError(
                    f"provider transport error ({type(exc).__name__})",
                    retryable=True,
                    attempts=attempt,
                )
            else:
                code = response.status_code
                if code < 400:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise ProviderError(
                            "provider returned a non-JSON response", attempts=attempt
                        ) from exc
                    if not isinstance(payload, dict):
                        raise ProviderError(
                            "provider returned an unexpected JSON shape", attempts=attempt
                        )
                    return payload
                retryable = code == 429 or code >= 500
                if not retryable:
                    raise ProviderError(
                        f"provider rejected the request (HTTP {code})",
                        status_code=code,
                        attempts=attempt,
                    )
                retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                error = ProviderError(
                    "model provider rate limited the run"
                    if code == 429
                    else f"provider server error (HTTP {code})",
                    retryable=True,
                    status_code=code,
                    attempts=attempt,
                )
            if attempt >= self.retry.max_attempts:
                raise error
            await self._sleep(self._delay(attempt, retry_after))

    async def _run_tool(
        self, environment: AgentEnvironment, call: Any, known: frozenset[str]
    ) -> tuple[str, bool]:
        """Return (content for the model, whether the tool actually executed)."""
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict) or not isinstance(function.get("name"), str):
            return "ERROR: malformed tool call (missing function name)", False
        name = function["name"]
        if name not in known:
            return f"ERROR: unknown or disabled tool: {name}", False
        raw = function.get("arguments")
        try:
            arguments = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
        except json.JSONDecodeError:
            return "ERROR: tool arguments were not valid JSON", False
        if not isinstance(arguments, dict):
            return "ERROR: tool arguments must be a JSON object", False
        try:
            result = await environment.call_tool(name, arguments)
        except ToolExecutionError as exc:
            return f"ERROR: {exc}", True
        return (result.content if result.success else f"ERROR: {result.error}"), True

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
        known = frozenset(tool.name for tool in environment.tools)
        usage = Usage()
        client = self._client or httpx.AsyncClient(timeout=60)
        owns_client = self._client is None
        tool_calls = 0  # executed by the environment
        attempted = 0  # includes malformed/unknown calls; this is what the cap bounds
        try:
            for step in range(1, self.configuration.max_steps + 1):
                started = time.monotonic()
                try:
                    payload = await self._post(
                        client,
                        endpoint,
                        {
                            "model": model.model,
                            "messages": messages,
                            "tools": tools,
                            "temperature": model.temperature,
                            "max_tokens": model.max_output_tokens,
                        },
                    )
                except ProviderError as exc:
                    await environment.record_model_call(
                        model.model,
                        (time.monotonic() - started) * 1000,
                        None,
                        None,
                        status="error",
                        error=self._redact(str(exc)),
                    )
                    raise
                raw_usage = payload.get("usage")
                token_data = raw_usage if isinstance(raw_usage, dict) else {}
                call_input = _token(token_data, "prompt_tokens")
                call_output = _token(token_data, "completion_tokens")
                details = token_data.get("prompt_tokens_details")
                cached = _token(details, "cached_tokens") if isinstance(details, dict) else None
                cached = cached if cached is not None else _token(token_data, "cached_tokens")
                await environment.record_model_call(
                    model.model, (time.monotonic() - started) * 1000, call_input, call_output
                )
                usage = Usage(
                    usage.model_calls + 1,
                    usage.input_tokens + (call_input or 0),
                    usage.output_tokens + (call_output or 0),
                    usage.cached_tokens + (cached or 0),
                    usage.unreported_calls + (1 if call_input is None else 0),
                )
                choices = payload.get("choices")
                message = (
                    choices[0].get("message")
                    if isinstance(choices, list) and choices and isinstance(choices[0], dict)
                    else None
                )
                if not isinstance(message, dict):
                    raise ProviderError("provider response had no choices[0].message")
                messages.append(message)
                requested = message.get("tool_calls")
                if not requested or not isinstance(requested, list):
                    content = message.get("content")
                    text = content if isinstance(content, str) and content else "finished"
                    return AgentResult(True, text, step, tool_calls, usage)
                for index, call in enumerate(requested):
                    if attempted >= self.max_tool_calls:
                        raise AgentLimitExceeded("max_tool_calls", self.max_tool_calls)
                    attempted += 1
                    content, executed = await self._run_tool(environment, call, known)
                    tool_calls += 1 if executed else 0
                    call_id = call.get("id") if isinstance(call, dict) else None
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id
                            if isinstance(call_id, str)
                            else f"call_{index}",
                            "content": content,
                        }
                    )
            raise AgentLimitExceeded("max_steps", self.configuration.max_steps)
        finally:
            if owns_client:
                await client.aclose()
