"""Chat-model interface, loopback guard, OpenAI-compatible and replay implementations."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx

from agentscope.agents.providers.retry import (
    RetryPolicy,
    Uniform,
    default_uniform,
    parse_retry_after,
)
from agentscope.domain.errors import LoopbackViolationError, ProviderError, SuiteDefinitionError
from agentscope.suites.models import GenerationParams, split_jsonl

PRESET_BASE_URLS: dict[str, str] = {
    "ollama": "http://127.0.0.1:11434/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
}
PROVIDERS = ("ollama", "lmstudio", "openai-compatible", "replay")
_LOOPBACK_PRESETS = frozenset(PRESET_BASE_URLS)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    """One model answer. Token counts and latency are None when not measured; never invented."""

    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: float | None = None
    finish_reason: str | None = None


class ChatModel(Protocol):
    async def complete(
        self, messages: list[ChatMessage], params: GenerationParams
    ) -> ChatCompletion: ...


@runtime_checkable
class CaseAwareChatModel(Protocol):
    """A model whose answer depends on the case id (replay), not on the prompt."""

    async def complete_for_case(
        self, case_id: str, messages: list[ChatMessage], params: GenerationParams
    ) -> ChatCompletion: ...


# ---------------------------------------------------------------- loopback guard


def require_loopback(url: str) -> str:
    """Return `url` unchanged iff it targets this machine; otherwise raise.

    Allowed: http/https to `localhost`, an IPv4 address in 127.0.0.0/8, or `::1`.
    No DNS lookup is performed: names other than the literal `localhost` are rejected
    outright, so `127.0.0.1.example.com` cannot pass. (`localhost` itself is resolved
    by the OS resolver when connecting; that is the one accepted trust assumption.)
    """
    if any(ch.isspace() or ch == "\\" or ord(ch) < 32 for ch in url):
        raise LoopbackViolationError("URL contains whitespace, control or backslash characters")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        _ = parts.port  # raises ValueError when malformed
    except ValueError as exc:
        raise LoopbackViolationError(f"URL is not parseable: {exc}") from exc
    if parts.scheme not in {"http", "https"}:
        raise LoopbackViolationError(f"scheme {parts.scheme!r} not allowed; use http or https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise LoopbackViolationError("URLs with embedded credentials (userinfo) are not allowed")
    if parts.query or parts.fragment or "?" in url or "#" in url:
        raise LoopbackViolationError("base URLs must not carry a query or fragment")
    if not host:
        raise LoopbackViolationError("URL has no host")
    if "%" in host:
        raise LoopbackViolationError("host must not carry a zone id")
    if host == "localhost":
        return url
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise LoopbackViolationError(
            f"host {host!r} is not loopback (allowed: localhost, 127.0.0.0/8, ::1)"
        ) from None
    if isinstance(address, ipaddress.IPv4Address):
        if address in ipaddress.ip_network("127.0.0.0/8"):
            return url
    elif address == ipaddress.IPv6Address("::1"):
        return url
    raise LoopbackViolationError(
        f"address {host} is not loopback (allowed: localhost, 127.0.0.0/8, ::1)"
    )


def redact(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def url_host(url: str) -> str:
    """host[:port] only; never userinfo, path or query."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    return f"{host}:{port}" if port else host


# ------------------------------------------------------- OpenAI-compatible model

SleepFn = Callable[[float], Awaitable[None]]
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class OpenAICompatibleChatModel:
    """Non-streaming `/chat/completions` client with bounded retry.

    The retry policy is shared with the agent provider (`agents.providers.retry`): only
    replay-safe transport errors (connect/write/read errors, protocol errors, pool timeouts),
    HTTP 429 and 5xx are retried, with capped exponential backoff and full jitter, `Retry-After`
    honoured (floored at the backoff base, capped). A ReadTimeout is not retried unless
    `AGENTSCOPE_PROVIDER_RETRY_READ_TIMEOUT` is set. Other 4xx, unsupported URLs and malformed
    bodies fail at once. Attempts default to 3. Redirects are not followed. The API key (read
    from an environment variable) is only ever placed in the Authorization header and is
    scrubbed from every error message.

    Timeouts: `request_timeout_seconds` bounds ONE HTTP attempt. The suite runner's
    `case_timeout_seconds` is a deliberate budget for the whole case (all attempts plus backoff),
    so keep the request timeout smaller than the case timeout or retries can never happen.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key_env: str | None = None,
        request_timeout_seconds: float = 60.0,
        max_attempts: int = 3,
        retry: RetryPolicy | None = None,
        sleep: SleepFn = asyncio.sleep,
        uniform: Uniform = default_uniform,
        client: httpx.AsyncClient | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.retry = retry or RetryPolicy.from_settings(max_attempts)
        self.request_timeout_seconds = request_timeout_seconds
        self._sleep = sleep
        self._uniform = uniform
        self._client = client
        self._api_key: str | None = None
        if api_key_env:
            key = (environ if environ is not None else os.environ).get(api_key_env)
            if not key:
                raise ProviderError(f"environment variable {api_key_env} is not set or empty")
            self._api_key = key

    @property
    def secrets(self) -> tuple[str, ...]:
        return (self._api_key,) if self._api_key else ()

    async def complete(
        self, messages: list[ChatMessage], params: GenerationParams
    ) -> ChatCompletion:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": params.temperature,
            "stream": False,
        }
        if params.max_tokens is not None:
            body["max_tokens"] = params.max_tokens
        if params.seed is not None:
            body["seed"] = params.seed
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        client = self._client or httpx.AsyncClient(
            timeout=self.request_timeout_seconds, follow_redirects=False, trust_env=False
        )
        try:
            return await self._with_retry(client, body, headers)
        finally:
            if self._client is None:
                await client.aclose()

    async def _with_retry(
        self, client: httpx.AsyncClient, body: dict[str, Any], headers: dict[str, str]
    ) -> ChatCompletion:
        attempt = 0
        while True:
            attempt += 1
            started = time.monotonic()
            retry_after: float | None = None
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=body, headers=headers
                )
            except httpx.InvalidURL as exc:
                raise ProviderError("provider endpoint URL is invalid", attempts=attempt) from exc
            except httpx.TransportError as exc:
                retryable = self.retry.is_retryable_transport(exc)
                error = ProviderError(
                    self._scrub(f"transport error ({type(exc).__name__}): {exc}"),
                    retryable=retryable,
                    attempts=attempt,
                )
                if not retryable:
                    raise error from exc
            else:
                latency_ms = (time.monotonic() - started) * 1000
                code = response.status_code
                if code < 300:
                    return self._parse(response, latency_ms)
                message = self._scrub(f"HTTP {code}: {response.text[:200]}")
                if code not in RETRYABLE_STATUS:
                    raise ProviderError(message, status_code=code, attempts=attempt)
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                error = ProviderError(message, status_code=code, retryable=True, attempts=attempt)
            if attempt >= self.retry.max_attempts:
                raise ProviderError(
                    f"{error} (after {attempt} attempts)",
                    status_code=error.status_code,
                    retryable=error.retryable,
                    attempts=attempt,
                )
            await self._sleep(self.retry.delay(attempt, retry_after, self._uniform))

    def _scrub(self, text: str) -> str:
        return redact(text, self.secrets)

    def _parse(self, response: httpx.Response, latency_ms: float) -> ChatCompletion:
        try:
            payload = response.json()
            choice = payload["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self._scrub(f"malformed completion response: {exc!r}")) from exc
        if not isinstance(content, str):
            raise ProviderError("completion has no text content")
        usage = payload.get("usage") if isinstance(payload, dict) else None
        finish = choice.get("finish_reason")
        model = payload.get("model")
        return ChatCompletion(
            text=content,
            model=model if isinstance(model, str) else self.model,
            prompt_tokens=_token(usage, "prompt_tokens"),
            completion_tokens=_token(usage, "completion_tokens"),
            latency_ms=latency_ms,
            finish_reason=finish if isinstance(finish, str) else None,
        )


def _token(usage: object, key: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


# ------------------------------------------------------------------ replay model


class ReplayChatModel:
    """Serves previously recorded `{id, output}` lines. Nothing is generated.

    Used for deterministic demos/tests and for re-scoring existing outputs. Latency and
    tokens are unknown (None). Runs using it are labelled `source: replay`.
    """

    def __init__(self, outputs: Mapping[str, str]) -> None:
        self._outputs = dict(outputs)
        self.used: set[str] = set()

    @classmethod
    def from_jsonl(cls, path: Path) -> ReplayChatModel:
        outputs: dict[str, str] = {}
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SuiteDefinitionError(f"cannot read replay outputs {path}: {exc}") from exc
        for number, line in enumerate(split_jsonl(text), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SuiteDefinitionError(
                    f"{path} line {number}: invalid JSON: {exc.msg}"
                ) from exc
            if (
                not isinstance(item, dict)
                or set(item) != {"id", "output"}
                or not isinstance(item["id"], str)
                or not isinstance(item["output"], str)
            ):
                raise SuiteDefinitionError(
                    f'{path} line {number}: expected exactly {{"id": str, "output": str}}'
                )
            if item["id"] in outputs:
                raise SuiteDefinitionError(f"{path} line {number}: duplicate id {item['id']!r}")
            outputs[item["id"]] = item["output"]
        return cls(outputs)

    def case_ids(self) -> list[str]:
        return list(self._outputs)

    def output_for(self, case_id: str) -> str | None:
        return self._outputs.get(case_id)

    @property
    def unused_ids(self) -> list[str]:
        return sorted(set(self._outputs) - self.used)

    async def complete(
        self, messages: list[ChatMessage], params: GenerationParams
    ) -> ChatCompletion:
        raise ProviderError("replay model needs a case id; use complete_for_case")

    async def complete_for_case(
        self, case_id: str, messages: list[ChatMessage], params: GenerationParams
    ) -> ChatCompletion:
        if case_id not in self._outputs:
            raise ProviderError(f"no replayed output for case id {case_id!r}")
        self.used.add(case_id)
        return ChatCompletion(text=self._outputs[case_id], model="replay", finish_reason="replay")


# ----------------------------------------------------------------------- factory


def build_chat_model(
    provider: str,
    model: str,
    *,
    base_url: str | None = None,
    local_only: bool = False,
    api_key_env: str | None = None,
    request_timeout_seconds: float = 60.0,
) -> OpenAICompatibleChatModel:
    """Build a network chat model. Presets always enforce loopback; so does `local_only`."""
    if provider in PRESET_BASE_URLS:
        url = base_url or PRESET_BASE_URLS[provider]
    elif provider == "openai-compatible":
        if not base_url:
            raise ProviderError("provider openai-compatible requires --base-url")
        url = base_url
    else:
        raise ProviderError(f"unknown provider {provider!r}; choose from {', '.join(PROVIDERS)}")
    if provider in _LOOPBACK_PRESETS or local_only:
        require_loopback(url)
    return OpenAICompatibleChatModel(
        url, model, api_key_env=api_key_env, request_timeout_seconds=request_timeout_seconds
    )
