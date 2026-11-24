"""Typed definitions for prompt suites: parameters, checker configuration, cases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Self

import regex
from pydantic import BaseModel, ConfigDict, Field, model_validator

SUITE_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{1,63}$"
CASE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
MAX_PATTERN_CHARS = 2000

CheckerType = Literal["exact", "regex", "field_lines", "json_keys"]

# Settings each checker type accepts. Anything else that is explicitly set is a
# configuration error, so a typo never silently disables a rule.
_ALLOWED_SETTINGS: dict[str, frozenset[str]] = {
    "exact": frozenset({"type", "case_insensitive"}),
    "regex": frozenset({"type", "pattern", "mode", "ignore_case", "timeout_seconds"}),
    "field_lines": frozenset({"type", "fields", "allowed_values", "strict_line_count", "ordered"}),
    "json_keys": frozenset({"type", "keys"}),
}


class GenerationParams(BaseModel):
    """Sampling parameters sent to the model. Part of the suite fingerprint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: float = Field(default=0.0, ge=0, le=2)
    seed: int | None = 0
    max_tokens: int | None = Field(default=512, ge=1, le=100_000)


class CheckerConfig(BaseModel):
    """Configuration for exactly one deterministic checker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: CheckerType
    # exact
    case_insensitive: bool = False
    # regex
    pattern: str | None = Field(default=None, min_length=1, max_length=MAX_PATTERN_CHARS)
    mode: Literal["fullmatch", "search"] = "fullmatch"
    ignore_case: bool = False
    timeout_seconds: float = Field(default=1.0, ge=0.01, le=30.0)
    # field_lines
    fields: tuple[str, ...] = ()
    allowed_values: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    strict_line_count: bool = True
    ordered: bool = True
    # json_keys
    keys: tuple[str, ...] = ()

    def effective(self) -> dict[str, Any]:
        """Only the settings that apply to this checker type (round-trips through validation)."""
        dumped = self.model_dump(mode="json")
        return {key: dumped[key] for key in dumped if key in _ALLOWED_SETTINGS[self.type]}

    @model_validator(mode="after")
    def _validate_for_type(self) -> Self:
        unexpected = self.model_fields_set - _ALLOWED_SETTINGS[self.type]
        if unexpected:
            raise ValueError(
                f"checker type {self.type!r} does not accept: {', '.join(sorted(unexpected))}"
            )
        if self.type == "regex":
            if self.pattern is None:
                raise ValueError("regex checker requires 'pattern'")
            try:
                regex.compile(self.pattern)
            except regex.error as exc:
                raise ValueError(f"invalid regex pattern: {exc}") from exc
        elif self.type == "field_lines":
            if not self.fields:
                raise ValueError("field_lines checker requires non-empty 'fields'")
            if any(not name or name != name.strip() or ":" in name for name in self.fields):
                raise ValueError("field names must be non-empty, trimmed and contain no ':'")
            if len(set(self.fields)) != len(self.fields):
                raise ValueError("field names must be unique")
            unknown = set(self.allowed_values) - set(self.fields)
            if unknown:
                raise ValueError(f"allowed_values for unknown fields: {', '.join(sorted(unknown))}")
            if any(not values for values in self.allowed_values.values()):
                raise ValueError("allowed_values lists must not be empty")
        elif self.type == "json_keys" and not self.keys:
            raise ValueError("json_keys checker requires non-empty 'keys'")
        return self


class SuiteDocument(BaseModel):
    """On-disk YAML shape of a prompt suite."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=SUITE_ID_PATTERN)
    kind: Literal["prompt_suite"]
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=64)
    cases: str = Field(min_length=1)
    system_prompt: str | None = None
    generation: GenerationParams = Field(default_factory=GenerationParams)
    checker: CheckerConfig


class CaseDocument(BaseModel):
    """One JSONL line of a cases file."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=CASE_ID_PATTERN)
    prompt: str
    reference: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SuiteCase:
    id: str
    prompt: str
    reference: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PromptSuite:
    id: str
    name: str
    version: str
    system_prompt: str | None
    generation: GenerationParams
    checker: CheckerConfig
    cases: tuple[SuiteCase, ...]
    fingerprint: str
    source_path: Path


def split_jsonl(text: str) -> list[str]:
    """Split on \\n only (dropping one trailing \\r): str.splitlines() also breaks on
    U+2028, U+0085, \\x1c and friends, which are legal inside JSON strings."""
    return [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]


def _frame(digest: Any, label: str, payload: bytes) -> None:
    # Length-prefixed framing so adjacent fields can never be confused.
    digest.update(label.encode() + b":" + str(len(payload)).encode() + b":")
    digest.update(payload)


def suite_fingerprint(
    suite_id: str,
    version: str,
    system_prompt: str | None,
    generation: GenerationParams,
    checker: CheckerConfig,
    cases_bytes: bytes,
) -> str:
    """sha256 over everything that changes what a run measures (not the display name)."""
    digest = hashlib.sha256()
    _frame(digest, "id", suite_id.encode())
    _frame(digest, "version", version.encode())
    _frame(digest, "system_prompt", (system_prompt or "").encode())
    _frame(digest, "has_system_prompt", b"1" if system_prompt is not None else b"0")
    _frame(
        digest,
        "generation",
        json.dumps(generation.model_dump(mode="json"), sort_keys=True).encode(),
    )
    _frame(
        digest,
        "checker",
        json.dumps(checker.effective(), sort_keys=True).encode(),
    )
    _frame(digest, "cases", cases_bytes)
    return digest.hexdigest()
