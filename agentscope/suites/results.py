"""results.json schema (written by the runner, read by compare)."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from agentscope.suites.models import CheckerConfig, GenerationParams

SCHEMA_VERSION = 1
RESULTS_NOTE = "Deterministic checks only; not a human preference judgement."


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldResult(_Doc):
    present: bool
    valid: bool
    matched: bool | None


class CheckResult(_Doc):
    passed: bool
    score: float = Field(ge=0, le=1)
    format_valid: bool
    fields: dict[str, FieldResult] | None
    detail: str


class CaseResultDoc(_Doc):
    id: str
    status: Literal["ok", "error"]
    error: str | None = None
    check: CheckResult | None = None
    output_chars: int | None = None
    output_sha256: str | None = None
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


class SuiteInfo(_Doc):
    id: str
    name: str
    version: str
    fingerprint: str
    checker: CheckerConfig
    n_cases: int

    @field_serializer("checker")
    def _serialize_checker(self, checker: CheckerConfig) -> dict[str, Any]:
        return checker.effective()


class RunInfo(_Doc):
    source: Literal["generated", "replay"]
    provider: str
    model: str
    base_url_host: str | None
    params: GenerationParams
    concurrency: int
    case_timeout_seconds: float
    trace_text: bool
    started_at: str
    finished_at: str
    replay_unused_ids: list[str] | None = None


class Percentiles(_Doc):
    p50: float | None
    p95: float | None
    method: str = "nearest-rank"
    n: int


class TokenTotals(_Doc):
    prompt: int | None
    completion: int | None
    cases_reporting: int


class Aggregate(_Doc):
    """Rates are over scored cases. `mean_score` (kept under this name for compatibility) is
    the mean *content* score: for field_lines it counts matched fields even when the output's
    format is invalid, so read it together with `format_valid_rate`."""

    n: int
    n_failed: int
    n_scored: int
    format_valid_rate: float | None
    pass_rate: float | None
    mean_score: float | None
    field_accuracy: dict[str, float | None]
    latency_ms: Percentiles
    tokens: TokenTotals


class ResultsDocument(_Doc):
    schema_version: int
    suite: SuiteInfo
    run: RunInfo
    cases: list[CaseResultDoc]
    aggregate: Aggregate
    note: str = RESULTS_NOTE


def nearest_rank(values: list[float], percent: float) -> float | None:
    """Nearest-rank percentile: the value at 1-based rank ceil(p/100 * n) of the sorted list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]
