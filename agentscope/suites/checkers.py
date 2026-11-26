"""Deterministic answer checkers. Pure functions; no model, no network, no judge.

Every checker tolerates leading/trailing whitespace and one wrapping markdown code
fence. None tolerates chatty preambles: prose around the answer makes it fail format.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import regex

from agentscope.suites.models import CheckerConfig

# Checkers never look at more than this many characters of model output, which
# bounds worst-case regex time on pathological output.
MAX_CHECK_CHARS = 100_000

_FENCE = re.compile(r"\A```[A-Za-z0-9_+-]*[ \t]*\n(.*?)\n?```\Z", re.DOTALL)


@dataclass(frozen=True, slots=True)
class FieldCheck:
    """Outcome for one configured field.

    present: the field line appeared at least once.
    valid: present and its value is non-empty and within allowed_values (if any).
    matched: equals the reference value (normalised, case-insensitive); None when
        the case has no reference.
    """

    present: bool
    valid: bool
    matched: bool | None


@dataclass(frozen=True, slots=True)
class CaseCheck:
    passed: bool
    score: float
    format_valid: bool
    fields: dict[str, FieldCheck] | None
    detail: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be within [0, 1]")


class Checker(Protocol):
    def check(self, output: str, reference: str | None) -> CaseCheck: ...


def normalise(text: str, *, case_insensitive: bool = True) -> str:
    """NFC-normalise, collapse all whitespace runs to one space and trim."""
    collapsed = " ".join(unicodedata.normalize("NFC", text).split())
    return collapsed.casefold() if case_insensitive else collapsed


def unwrap_fence(text: str) -> str:
    """Trim whitespace and remove exactly one wrapping ``` fence, if present."""
    stripped = text.strip()
    match = _FENCE.match(stripped)
    if match and "```" not in match.group(1):
        return match.group(1).strip()
    return stripped


def _bounded(text: str) -> str:
    return text[:MAX_CHECK_CHARS]


class ExactChecker:
    def __init__(self, case_insensitive: bool = False) -> None:
        self.case_insensitive = case_insensitive

    def check(self, output: str, reference: str | None) -> CaseCheck:
        if reference is None:
            raise ValueError("exact checker requires a reference")
        got = normalise(unwrap_fence(_bounded(output)), case_insensitive=self.case_insensitive)
        if len(output) > MAX_CHECK_CHARS or len(reference) > MAX_CHECK_CHARS:
            # Comparing truncated text could pass two values that differ past the limit.
            return CaseCheck(
                passed=False,
                score=0.0,
                format_valid=bool(got),
                fields=None,
                detail=f"output or reference over {MAX_CHECK_CHARS} characters; not compared",
            )
        # Fences are removed from both sides, as FieldLinesChecker already does.
        want = normalise(unwrap_fence(reference), case_insensitive=self.case_insensitive)
        passed = got == want
        return CaseCheck(
            passed=passed,
            score=1.0 if passed else 0.0,
            format_valid=bool(got),
            fields=None,
            detail="equal after normalisation" if passed else "differs from reference",
        )


class RegexChecker:
    """Patterns use the `regex` module (a superset of `re`) so every match has a hard deadline.

    A pattern that exceeds `timeout_seconds` on an output is a failed check ("regex timed out"),
    never a hang.
    """

    def __init__(
        self,
        pattern: str,
        mode: str = "fullmatch",
        ignore_case: bool = False,
        timeout_seconds: float = 1.0,
    ) -> None:
        self._pattern = regex.compile(pattern, regex.IGNORECASE if ignore_case else 0)
        self._mode = mode
        self._timeout = timeout_seconds

    def check(self, output: str, reference: str | None) -> CaseCheck:
        # Only whitespace is trimmed here; the pattern author owns any fence handling.
        text = _bounded(output).strip()
        try:
            found = (
                self._pattern.fullmatch(text, timeout=self._timeout)
                if self._mode == "fullmatch"
                else self._pattern.search(text, timeout=self._timeout)
            )
        except TimeoutError:
            return CaseCheck(False, 0.0, False, None, "regex timed out")
        passed = found is not None
        return CaseCheck(
            passed=passed,
            score=1.0 if passed else 0.0,
            format_valid=passed,
            fields=None,
            detail=f"pattern {self._mode} {'matched' if passed else 'did not match'}",
        )


class JsonKeysChecker:
    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = keys

    def check(self, output: str, reference: str | None) -> CaseCheck:
        text = unwrap_fence(_bounded(output))
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, RecursionError):
            return CaseCheck(False, 0.0, False, None, "output is not valid JSON")
        if not isinstance(value, dict):
            return CaseCheck(False, 0.0, False, None, "JSON value is not an object")
        missing = [key for key in self.keys if key not in value]
        score = (len(self.keys) - len(missing)) / len(self.keys)
        if missing:
            return CaseCheck(False, score, False, None, f"missing keys: {', '.join(missing)}")
        return CaseCheck(True, 1.0, True, None, "valid JSON object with all required keys")


@dataclass(frozen=True, slots=True)
class ParsedFields:
    values: dict[str, list[str]]
    order: list[str]
    extra_lines: list[str]


def parse_field_lines(text: str, fields: tuple[str, ...]) -> ParsedFields:
    """Split text into `KEY: value` lines for configured KEYs (split on the first colon).

    Keys are case-sensitive and must touch the colon. Any other non-empty line is
    reported in extra_lines.
    """
    known = set(fields)
    values: dict[str, list[str]] = {}
    order: list[str] = []
    extra: list[str] = []
    for raw in re.split(r"\r?\n", text):
        line = raw.strip()
        if not line:
            continue
        key, sep, rest = line.partition(":")
        if sep and key in known:
            values.setdefault(key, []).append(rest.strip())
            order.append(key)
        else:
            extra.append(line)
    return ParsedFields(values, order, extra)


class FieldLinesChecker:
    """Checks a `KEY: value` card.

    format_valid iff: every configured field appears exactly once with a non-empty
    value inside allowed_values (case-sensitive); fields appear in configured order
    when ordered; and, when strict_line_count, there are no other non-empty lines.
    Per-field `matched` compares to the reference field (normalised, case-insensitive).
    score = matched fields / total fields, computed from whatever fields were parsed
    even when the format is invalid (so content-right/format-wrong is visible).
    Without a reference there is nothing to match: score is format-only (1.0 or 0.0).
    passed = format_valid and every field matched (or, without reference, format_valid).
    """

    def __init__(
        self,
        fields: tuple[str, ...],
        allowed_values: Mapping[str, tuple[str, ...]],
        strict_line_count: bool = True,
        ordered: bool = True,
    ) -> None:
        self.fields = fields
        self.allowed_values = allowed_values
        self.strict_line_count = strict_line_count
        self.ordered = ordered

    def check(self, output: str, reference: str | None) -> CaseCheck:
        parsed = parse_field_lines(unwrap_fence(_bounded(output)), self.fields)
        problems: list[str] = []
        ref_values: dict[str, str] | None = None
        if reference is not None:
            ref_parsed = parse_field_lines(unwrap_fence(reference), self.fields)
            ref_values = {k: v[0] for k, v in ref_parsed.values.items()}

        results: dict[str, FieldCheck] = {}
        for name in self.fields:
            seen = parsed.values.get(name, [])
            if not seen:
                problems.append(f"missing {name}")
            elif len(seen) > 1:
                problems.append(f"duplicate {name}")
            first = seen[0] if seen else None
            valid = first is not None and first != ""
            if first is not None and first == "":
                problems.append(f"empty {name}")
            allowed = self.allowed_values.get(name)
            if valid and allowed is not None and first not in allowed:
                valid = False
                problems.append(f"{name} value not in allowed values")
            matched: bool | None = None
            if ref_values is not None:
                want = ref_values.get(name)
                matched = (
                    first is not None and want is not None and normalise(first) == normalise(want)
                )
            results[name] = FieldCheck(bool(seen), valid, matched)

        if self.ordered:
            expected = [name for name in self.fields if name in parsed.values]
            first_seen: list[str] = []
            for name in parsed.order:
                if name not in first_seen:
                    first_seen.append(name)
            if first_seen != expected:
                problems.append("fields out of order")
        if self.strict_line_count and parsed.extra_lines:
            problems.append(f"{len(parsed.extra_lines)} extra non-field line(s)")

        format_valid = not problems
        if ref_values is None:
            score = 1.0 if format_valid else 0.0
            passed = format_valid
        else:
            hits = sum(1 for item in results.values() if item.matched)
            score = hits / len(self.fields)
            passed = format_valid and hits == len(self.fields)
        if format_valid and passed:
            detail = "format valid; all fields match" if ref_values else "format valid"
        elif format_valid:
            wrong = [n for n, r in results.items() if not r.matched]
            detail = f"format valid; mismatched fields: {', '.join(wrong)}"
        else:
            detail = "; ".join(problems)
        return CaseCheck(passed, score, format_valid, results, detail)


def build_checker(config: CheckerConfig) -> Checker:
    if config.type == "exact":
        return ExactChecker(config.case_insensitive)
    if config.type == "regex":
        assert config.pattern is not None
        return RegexChecker(config.pattern, config.mode, config.ignore_case, config.timeout_seconds)
    if config.type == "field_lines":
        return FieldLinesChecker(
            config.fields, config.allowed_values, config.strict_line_count, config.ordered
        )
    return JsonKeysChecker(config.keys)
