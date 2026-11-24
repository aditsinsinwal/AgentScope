from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentscope.agents.providers.openai_compatible import (
    OpenAICompatibleAgent,
    RetryPolicy,
    _parse_retry_after,
)
from agentscope.domain.errors import AgentLimitExceeded, ProviderError, ToolExecutionError
from agentscope.domain.models import (
    AgentConfiguration,
    EvaluationTask,
    ModelConfiguration,
    TaskId,
)
from agentscope.execution.tools.models import ToolDefinition, ToolOutput

SECRET = "sk-super-secret-key"


class Env:
    def __init__(self, tool_names: tuple[str, ...] = ("read_file",)) -> None:
        self.tools = tuple(ToolDefinition(n, "d", {"type": "object"}, 1) for n in tool_names)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.model_events: list[tuple[int | None, int | None, str, str | None]] = []
        self.raise_tool_error = False

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutput:
        if self.raise_tool_error:
            raise ToolExecutionError("boom")
        self.calls.append((name, arguments))
        return ToolOutput(True, "file-content", 1.0)

    async def record_model_call(
        self,
        model: str,
        duration_ms: float,
        input_tokens: int | None,
        output_tokens: int | None,
        *,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        self.model_events.append((input_tokens, output_tokens, status, error))


def make_task(tmp_path: Path) -> EvaluationTask:
    return EvaluationTask(TaskId("t"), "T", tmp_path, "Do it", ("pytest",), ("pytest",))


def make_agent(
    handler: Callable[[httpx.Request], httpx.Response],
    sleeps: list[float] | None = None,
    *,
    max_steps: int = 5,
    max_attempts: int = 4,
    max_tool_calls: int | None = None,
) -> tuple[OpenAICompatibleAgent, httpx.AsyncClient]:
    async def fake_sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    configuration = AgentConfiguration(
        "c", ModelConfiguration("p", "m", "https://provider.invalid/v1"), max_steps=max_steps
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    agent = OpenAICompatibleAgent(
        configuration,
        SECRET,
        client=client,
        retry=RetryPolicy(max_attempts, 1.0, 10.0),
        sleep=fake_sleep,
        uniform=lambda low, high: high,  # deterministic: always the jitter ceiling
        max_tool_calls=max_tool_calls,
    )
    return agent, client


def ok(message: dict[str, Any], usage: dict[str, Any] | None = None) -> httpx.Response:
    body: dict[str, Any] = {"choices": [{"message": message}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def tool_call(name: str, arguments: str, call_id: str = "c1") -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


async def test_retries_5xx_then_succeeds_with_exponential_ceiling(tmp_path: Path) -> None:
    statuses = iter([500, 503, 200])
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return ok({"content": "done"}) if status == 200 else httpx.Response(status)

    agent, client = make_agent(handler, sleeps)
    async with client:
        result = await agent.run(make_task(tmp_path), Env())
    assert result.completed and result.message == "done"
    assert sleeps == [1.0, 2.0]  # base * 2**(attempt-1), jitter ceiling


async def test_backoff_is_capped_and_attempts_bounded(tmp_path: Path) -> None:
    sleeps: list[float] = []
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502, text=f"upstream said {SECRET}")

    agent, client = make_agent(handler, sleeps, max_attempts=6)
    env = Env()
    async with client:
        with pytest.raises(ProviderError) as info:
            await agent.run(make_task(tmp_path), env)
    assert calls == 6 and info.value.attempts == 6
    assert info.value.retryable and info.value.status_code == 502
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 10.0]  # capped at cap_seconds
    assert SECRET not in str(info.value)
    assert env.model_events[-1][2] == "error"
    assert SECRET not in (env.model_events[-1][3] or "")


async def test_429_honours_retry_after_capped(tmp_path: Path) -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(429, headers={"Retry-After": "9999"}),
            ok({"content": "x"}),
        ]
    )
    sleeps: list[float] = []
    agent, client = make_agent(lambda _: next(responses), sleeps)
    async with client:
        await agent.run(make_task(tmp_path), Env())
    assert sleeps == [3.0, 10.0]


async def test_exhausted_429_has_rate_limit_message(tmp_path: Path) -> None:
    agent, client = make_agent(lambda _: httpx.Response(429), max_attempts=2)
    async with client:
        with pytest.raises(ProviderError, match="rate limited") as info:
            await agent.run(make_task(tmp_path), Env())
    assert info.value.status_code == 429 and info.value.retryable


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_other_4xx_never_retried(tmp_path: Path, status: int) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": f"bad key {SECRET}"}})

    agent, client = make_agent(handler)
    async with client:
        with pytest.raises(ProviderError) as info:
            await agent.run(make_task(tmp_path), Env())
    assert calls == 1 and not info.value.retryable and info.value.status_code == status
    assert SECRET not in str(info.value)


async def test_transport_errors_retried_without_leaking_details(tmp_path: Path) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError(f"cannot connect {SECRET}", request=request)
        return ok({"content": "ok"})

    agent, client = make_agent(handler)
    async with client:
        assert (await agent.run(make_task(tmp_path), Env())).completed
    assert attempts == 3


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{}]}),
        httpx.Response(200, json={"choices": ["x"]}),
    ],
)
async def test_malformed_response_is_typed_non_retryable(
    tmp_path: Path, response: httpx.Response
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    agent, client = make_agent(handler)
    async with client:
        with pytest.raises(ProviderError) as info:
            await agent.run(make_task(tmp_path), Env())
    assert calls == 1 and not info.value.retryable


async def test_null_content_and_missing_usage_are_not_invented(tmp_path: Path) -> None:
    agent, client = make_agent(lambda _: ok({"role": "assistant", "content": None}))
    env = Env()
    async with client:
        result = await agent.run(make_task(tmp_path), env)
    assert result.message == "finished"
    assert env.model_events == [(None, None, "success", None)]
    assert result.usage.input_tokens == 0 and result.usage.unreported_calls == 1


async def test_non_integer_usage_ignored_and_nested_cached_tokens(tmp_path: Path) -> None:
    usage = {
        "prompt_tokens": "7",
        "completion_tokens": True,
        "prompt_tokens_details": {"cached_tokens": 4},
    }
    agent, client = make_agent(lambda _: ok({"content": "x"}, usage))
    env = Env()
    async with client:
        result = await agent.run(make_task(tmp_path), env)
    assert env.model_events[0][:2] == (None, None)
    assert result.usage.cached_tokens == 4


async def test_tool_loop_survives_bad_calls(tmp_path: Path) -> None:
    sequence = iter(
        [
            ok(
                {
                    "content": None,
                    "tool_calls": [
                        tool_call("read_file", "{not json", "a"),
                        tool_call("rm_rf", "{}", "b"),
                        tool_call("read_file", "[1]", "c"),
                        {"id": "d"},
                        tool_call("read_file", '{"path": "x"}', "e"),
                        tool_call("read_file", "", "f"),
                    ],
                }
            ),
            ok({"content": "all done"}),
        ]
    )
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return next(sequence)

    agent, client = make_agent(handler)
    env = Env()
    async with client:
        result = await agent.run(make_task(tmp_path), env)
    assert result.completed and result.message == "all done"
    assert env.calls == [("read_file", {"path": "x"}), ("read_file", {})]
    assert result.tool_calls == 2
    tool_messages = [m for m in bodies[1]["messages"] if m.get("role") == "tool"]
    contents = [m["content"] for m in tool_messages]
    assert "not valid JSON" in contents[0]
    assert "unknown or disabled tool: rm_rf" in contents[1]
    assert "JSON object" in contents[2]
    assert "malformed tool call" in contents[3]
    assert contents[4] == "file-content"
    assert [m["tool_call_id"] for m in tool_messages][3] == "d"


async def test_tool_execution_error_is_recorded_not_fatal(tmp_path: Path) -> None:
    sequence = iter(
        [ok({"tool_calls": [tool_call("read_file", "{}")]}), ok({"content": "recovered"})]
    )
    agent, client = make_agent(lambda _: next(sequence))
    env = Env()
    env.raise_tool_error = True
    async with client:
        result = await agent.run(make_task(tmp_path), env)
    assert result.completed and result.tool_calls == 1


async def test_step_cap_is_distinct_terminal_outcome(tmp_path: Path) -> None:
    agent, client = make_agent(
        lambda _: ok({"tool_calls": [tool_call("read_file", "{}")]}), max_steps=3
    )
    async with client:
        with pytest.raises(AgentLimitExceeded) as info:
            await agent.run(make_task(tmp_path), Env())
    assert info.value.limit == "max_steps" and "limit_exceeded" in str(info.value)


async def test_tool_call_cap_counts_bad_calls_too(tmp_path: Path) -> None:
    message = {"tool_calls": [tool_call("nope", "{}", f"c{i}") for i in range(5)]}
    agent, client = make_agent(lambda _: ok(message), max_steps=50, max_tool_calls=7)
    async with client:
        with pytest.raises(AgentLimitExceeded) as info:
            await agent.run(make_task(tmp_path), Env())
    assert info.value.limit == "max_tool_calls"


async def test_constructor_validation(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleAgent(AgentConfiguration("c"), "k")
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(base_seconds=-1)


def test_retry_after_parsing() -> None:
    assert _parse_retry_after(None) is None
    assert _parse_retry_after(" 2.5 ") == 2.5
    assert _parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert _parse_retry_after("-1") is None
    assert _parse_retry_after("nan") is None
    assert _parse_retry_after("inf") is None


def test_retry_policy_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentscope.config import get_settings

    monkeypatch.setenv("AGENTSCOPE_PROVIDER_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()
    try:
        assert RetryPolicy.from_settings().max_attempts == 2
    finally:
        get_settings.cache_clear()


def _raiser(error_type: type[Exception], counter: list[int]) -> Callable[[httpx.Request], Any]:
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        raise (
            error_type("x", request=request)
            if error_type is not httpx.InvalidURL
            else error_type("x")
        )  # type: ignore[call-arg]

    return handler


@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.RemoteProtocolError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.PoolTimeout,
    ],
)
async def test_safe_transport_errors_are_retried(
    tmp_path: Path, error_type: type[Exception]
) -> None:
    calls: list[int] = []
    agent, client = make_agent(_raiser(error_type, calls), max_attempts=3)
    async with client:
        with pytest.raises(ProviderError) as info:
            await agent.run(make_task(tmp_path), Env())
    assert len(calls) == 3 and info.value.retryable


@pytest.mark.parametrize(
    "error_type", [httpx.ReadTimeout, httpx.UnsupportedProtocol, httpx.InvalidURL]
)
async def test_unsafe_transport_errors_are_not_retried(
    tmp_path: Path, error_type: type[Exception]
) -> None:
    calls: list[int] = []
    agent, client = make_agent(_raiser(error_type, calls))
    async with client:
        with pytest.raises(ProviderError) as info:
            await agent.run(make_task(tmp_path), Env())
    assert len(calls) == 1 and not info.value.retryable


async def test_read_timeout_retry_is_opt_in(tmp_path: Path) -> None:
    calls: list[int] = []
    agent, client = make_agent(_raiser(httpx.ReadTimeout, calls), max_attempts=2)
    agent.retry = RetryPolicy(2, 1.0, 10.0, retry_read_timeout=True)
    async with client:
        with pytest.raises(ProviderError):
            await agent.run(make_task(tmp_path), Env())
    assert len(calls) == 2


async def test_retry_after_zero_is_floored_at_backoff_base(tmp_path: Path) -> None:
    responses = iter([httpx.Response(429, headers={"Retry-After": "0"}), ok({"content": "x"})])
    sleeps: list[float] = []
    agent, client = make_agent(lambda _: next(responses), sleeps)
    async with client:
        await agent.run(make_task(tmp_path), Env())
    assert sleeps == [1.0]


@pytest.mark.parametrize("bad", ["call it", {"id": "x"}, 5])
async def test_non_list_tool_calls_is_not_a_final_answer(tmp_path: Path, bad: object) -> None:
    agent, client = make_agent(lambda _: ok({"content": "done", "tool_calls": bad}))
    async with client:
        with pytest.raises(ProviderError, match="tool_calls") as info:
            await agent.run(make_task(tmp_path), Env())
    assert not info.value.retryable


def test_zero_tool_call_cap_is_rejected() -> None:
    config = AgentConfiguration("c", ModelConfiguration("p", "m"))
    with pytest.raises(ValueError, match="max_tool_calls"):
        OpenAICompatibleAgent(config, "k", max_tool_calls=0)
