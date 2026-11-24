import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentscope.domain.errors import LoopbackViolationError, ProviderError, SuiteDefinitionError
from agentscope.suites.models import GenerationParams
from agentscope.suites.providers import (
    ChatMessage,
    OpenAICompatibleChatModel,
    ReplayChatModel,
    build_chat_model,
    require_loopback,
    url_host,
)

PARAMS = GenerationParams(temperature=0, seed=7, max_tokens=50)
MESSAGES = [ChatMessage("system", "s"), ChatMessage("user", "hi")]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434/v1",
        "http://localhost:1234/v1",
        "https://localhost/v1",
        "http://127.1.2.3/v1",
        "http://[::1]:8080/v1",
        "HTTP://LOCALHOST:1/v1",
    ],
)
def test_loopback_allowed(url: str) -> None:
    assert require_loopback(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1.example.com/v1",
        "http://localhost.evil.com/v1",
        "http://0.0.0.0:11434/v1",
        "http://127.0.0.1@evil.com/v1",
        "http://user:pw@127.0.0.1/v1",
        "http://evil.com#@127.0.0.1/",
        "http://127.0.0.1\\@evil.com/",
        "http://[::2]/v1",
        "http://[::ffff:127.0.0.1]/v1",
        "http://[::1%25eth0]/v1",
        "http://128.0.0.1/v1",
        "http://10.0.0.5/v1",
        "http://192.168.1.2:1234/v1",
        "http://127.1/v1",
        "http://2130706433/v1",
        "ftp://127.0.0.1/",
        "file:///etc/passwd",
        "127.0.0.1:11434/v1",
        "http:///v1",
        "http://127.0.0.1:notaport/v1",
        "http://127.0.0.1/ v1",
        "https://api.openai.com/v1",
    ],
)
def test_loopback_rejected(url: str) -> None:
    with pytest.raises(LoopbackViolationError):
        require_loopback(url)


def test_url_host_drops_userinfo_and_path() -> None:
    assert url_host("http://127.0.0.1:11434/v1/secret?x=1") == "127.0.0.1:11434"
    assert url_host("http://[::1]:80/v1") == "[::1]:80"
    assert url_host("https://example.com/v1") == "example.com"


def test_presets_always_enforce_loopback() -> None:
    assert build_chat_model("ollama", "m").base_url == "http://127.0.0.1:11434/v1"
    assert build_chat_model("lmstudio", "m").base_url == "http://127.0.0.1:1234/v1"
    with pytest.raises(LoopbackViolationError):
        build_chat_model("ollama", "m", base_url="https://api.openai.com/v1")
    with pytest.raises(LoopbackViolationError):
        build_chat_model("lmstudio", "m", base_url="http://10.1.1.1:1234/v1", local_only=False)


def test_openai_compatible_requires_base_url_and_honours_local_only() -> None:
    with pytest.raises(ProviderError, match="--base-url"):
        build_chat_model("openai-compatible", "m")
    remote = "https://api.example.com/v1"
    assert build_chat_model("openai-compatible", "m", base_url=remote).base_url == remote
    with pytest.raises(LoopbackViolationError):
        build_chat_model("openai-compatible", "m", base_url=remote, local_only=True)
    build_chat_model("openai-compatible", "m", base_url="http://localhost:9/v1", local_only=True)
    with pytest.raises(ProviderError, match="unknown provider"):
        build_chat_model("nope", "m")


def model_with(handler: Any, **kwargs: Any) -> tuple[OpenAICompatibleChatModel, list[float]]:
    sleeps: list[float] = []

    async def sleep(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    model = OpenAICompatibleChatModel(
        "http://127.0.0.1:1/v1/", "demo", client=client, sleep=sleep, **kwargs
    )
    return model, sleeps


def ok_body(**extra: Any) -> dict[str, Any]:
    body = {
        "model": "demo-served",
        "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
    }
    body.update(extra)
    return body


async def test_success_request_shape_and_usage() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=ok_body())

    model, _ = model_with(handler)
    result = await model.complete(MESSAGES, PARAMS)
    assert seen["url"] == "http://127.0.0.1:1/v1/chat/completions"
    assert seen["auth"] is None
    assert seen["body"] == {
        "model": "demo",
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}],
        "temperature": 0.0,
        "stream": False,
        "max_tokens": 50,
        "seed": 7,
    }
    assert (result.text, result.model, result.finish_reason) == ("hello", "demo-served", "stop")
    assert (result.prompt_tokens, result.completion_tokens) == (11, 3)
    assert result.latency_ms is not None and result.latency_ms >= 0


@pytest.mark.parametrize(
    "usage", [None, {}, {"prompt_tokens": None, "completion_tokens": "7"}, {"prompt_tokens": -1}]
)
async def test_missing_or_invalid_usage_is_none_not_invented(usage: Any) -> None:
    body = ok_body()
    if usage is None:
        del body["usage"]
    else:
        body["usage"] = usage
    model, _ = model_with(lambda request: httpx.Response(200, json=body))
    result = await model.complete(MESSAGES, PARAMS)
    assert result.prompt_tokens is None and result.completion_tokens is None


async def test_retries_5xx_then_succeeds_with_backoff() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503 if len(calls) == 1 else 429, text="busy")
        return httpx.Response(200, json=ok_body())

    model, sleeps = model_with(handler, base_delay_seconds=1.0)
    assert (await model.complete(MESSAGES, PARAMS)).text == "hello"
    assert len(calls) == 3 and sleeps == [1.0, 2.0]


async def test_retries_transport_errors_and_gives_up_after_three() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("refused")

    model, sleeps = model_with(handler)
    with pytest.raises(ProviderError, match="after 3 attempts") as info:
        await model.complete(MESSAGES, PARAMS)
    assert len(calls) == 3 and len(sleeps) == 2 and info.value.retryable


async def test_4xx_not_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, text="bad model")

    model, sleeps = model_with(handler)
    with pytest.raises(ProviderError, match="HTTP 400") as info:
        await model.complete(MESSAGES, PARAMS)
    assert len(calls) == 1 and sleeps == [] and info.value.status_code == 400
    assert not info.value.retryable


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        httpx.Response(302, headers={"location": "http://evil.example/"}),
    ],
)
async def test_malformed_and_redirect_fail_without_retry(response: httpx.Response) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return response

    model, _ = model_with(handler)
    with pytest.raises(ProviderError):
        await model.complete(MESSAGES, PARAMS)
    assert len(calls) == 1


async def test_api_key_header_and_never_in_errors() -> None:
    secret = "sk-test-SECRET-123"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {secret}"
        return httpx.Response(401, text=f"invalid key {secret}")

    model, _ = model_with(handler, api_key_env="MY_KEY", environ={"MY_KEY": secret})
    with pytest.raises(ProviderError) as info:
        await model.complete(MESSAGES, PARAMS)
    assert secret not in str(info.value) and "[REDACTED]" in str(info.value)
    assert model.secrets == (secret,)


def test_missing_api_key_env_is_an_error_without_leaking() -> None:
    with pytest.raises(ProviderError, match="MY_KEY"):
        OpenAICompatibleChatModel("http://127.0.0.1/v1", "m", api_key_env="MY_KEY", environ={})


async def test_replay_model(tmp_path: Path) -> None:
    path = tmp_path / "o.jsonl"
    path.write_text('{"id":"a","output":"x"}\n\n{"id":"b","output":"y"}\n', encoding="utf-8")
    replay = ReplayChatModel.from_jsonl(path)
    result = await replay.complete_for_case("a", MESSAGES, PARAMS)
    assert (result.text, result.model, result.latency_ms, result.prompt_tokens) == (
        "x",
        "replay",
        None,
        None,
    )
    assert replay.unused_ids == ["b"]
    with pytest.raises(ProviderError, match="no replayed output"):
        await replay.complete_for_case("zzz", MESSAGES, PARAMS)
    with pytest.raises(ProviderError):
        await replay.complete(MESSAGES, PARAMS)


@pytest.mark.parametrize(
    "text",
    [
        '{"id":"a"}',
        '{"id":"a","output":1}',
        '{"id":"a","output":"x","n":1}',
        "oops",
        '{"id":"a","output":"x"}\n{"id":"a","output":"y"}',
    ],
)
def test_replay_file_validation(tmp_path: Path, text: str) -> None:
    path = tmp_path / "o.jsonl"
    path.write_text(text + "\n")
    with pytest.raises(SuiteDefinitionError, match="line"):
        ReplayChatModel.from_jsonl(path)
