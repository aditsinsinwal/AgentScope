"""Retry policy shared by every OpenAI-compatible provider (agent loop and prompt suites)."""

from __future__ import annotations

import random as _random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from agentscope.config import get_settings

Sleep = Callable[[float], Awaitable[None]]
Uniform = Callable[[float, float], float]
default_uniform: Uniform = _random.uniform


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded exponential backoff with full jitter."""

    max_attempts: int = 4
    base_seconds: float = 0.5
    cap_seconds: float = 30.0
    # A ReadTimeout means the request was sent and may still be processed (and billed); resending
    # it can duplicate a completion, so it is opt-in.
    retry_read_timeout: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_seconds < 0 or self.cap_seconds < 0:
            raise ValueError("backoff durations must not be negative")

    @classmethod
    def from_settings(cls, max_attempts: int | None = None) -> RetryPolicy:
        settings = get_settings()
        return cls(
            max_attempts if max_attempts is not None else settings.provider_max_attempts,
            settings.provider_backoff_base_seconds,
            settings.provider_backoff_cap_seconds,
            settings.provider_retry_read_timeout,
        )

    def is_retryable_transport(self, exc: httpx.TransportError) -> bool:
        return isinstance(exc, RETRYABLE_TRANSPORT) or (
            self.retry_read_timeout and isinstance(exc, httpx.ReadTimeout)
        )

    def delay(self, attempt: int, retry_after: float | None, uniform: Uniform) -> float:
        if retry_after is not None:
            # Floor at the backoff base so "Retry-After: 0" cannot turn into a hot loop.
            return min(max(retry_after, self.base_seconds), self.cap_seconds)
        ceiling = min(self.cap_seconds, self.base_seconds * (2 ** (attempt - 1)))
        return uniform(0.0, ceiling)


# Failures where resending is safe: the request was not (fully) delivered or the connection broke.
RETRYABLE_TRANSPORT = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.PoolTimeout,
)


def parse_retry_after(value: str | None) -> float | None:
    """Seconds form only; HTTP-date values are ignored in favour of computed backoff."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 and seconds == seconds and seconds != float("inf") else None
