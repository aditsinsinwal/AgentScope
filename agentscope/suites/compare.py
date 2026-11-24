"""Paired comparison of two results.json documents. Counts only; no significance claims."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentscope.domain.errors import SuiteComparisonError
from agentscope.suites.results import ResultsDocument

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Comparison:
    suite_id: str
    fingerprint_match: bool
    warnings: tuple[str, ...]
    n_paired: int
    n_unpaired: int  # cases missing or failed on at least one side
    b_better: int
    tie: int
    a_better: int
    # Paired format/pass counts: cases where only one side was format-valid / passed.
    format_valid_b_only: int
    format_valid_a_only: int
    passed_b_only: int
    passed_a_only: int
    format_valid_rate_delta: float | None  # b - a
    pass_rate_delta: float | None
    mean_score_delta: float | None
    field_accuracy_delta: dict[str, float | None] = field(default_factory=dict)
    a_source: str = "generated"
    b_source: str = "generated"


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


def compare_results(
    a: ResultsDocument, b: ResultsDocument, *, allow_mismatch: bool = False
) -> Comparison:
    warnings: list[str] = []
    match = a.suite.fingerprint == b.suite.fingerprint
    if not match:
        if not allow_mismatch:
            raise SuiteComparisonError(
                "suite fingerprints differ "
                f"({a.suite.fingerprint[:12]} vs {b.suite.fingerprint[:12]}); the runs measured "
                "different suites. Pass --allow-mismatch to compare anyway."
            )
        warnings.append("suite fingerprints differ; comparison covers only shared case ids")
    for label, doc in (("A", a), ("B", b)):
        if doc.run.source == "replay":
            warnings.append(f"{label} is a replay of recorded outputs, not a generated run")
    by_a = {c.id: c for c in a.cases}
    by_b = {c.id: c for c in b.cases}
    better_b = tie = better_a = unpaired = 0
    fmt_b = fmt_a = pass_b = pass_a = 0
    for case_id in sorted(set(by_a) | set(by_b)):
        ca, cb = by_a.get(case_id), by_b.get(case_id)
        if not (ca and cb and ca.check and cb.check):
            unpaired += 1
            continue
        fmt_b += cb.check.format_valid and not ca.check.format_valid
        fmt_a += ca.check.format_valid and not cb.check.format_valid
        pass_b += cb.check.passed and not ca.check.passed
        pass_a += ca.check.passed and not cb.check.passed
        diff = cb.check.score - ca.check.score
        if diff > _EPS:
            better_b += 1
        elif diff < -_EPS:
            better_a += 1
        else:
            tie += 1
    fields = sorted(set(a.aggregate.field_accuracy) | set(b.aggregate.field_accuracy))
    return Comparison(
        suite_id=a.suite.id,
        fingerprint_match=match,
        warnings=tuple(warnings),
        n_paired=better_b + tie + better_a,
        n_unpaired=unpaired,
        b_better=better_b,
        tie=tie,
        a_better=better_a,
        format_valid_b_only=fmt_b,
        format_valid_a_only=fmt_a,
        passed_b_only=pass_b,
        passed_a_only=pass_a,
        format_valid_rate_delta=_delta(
            a.aggregate.format_valid_rate, b.aggregate.format_valid_rate
        ),
        pass_rate_delta=_delta(a.aggregate.pass_rate, b.aggregate.pass_rate),
        mean_score_delta=_delta(a.aggregate.mean_score, b.aggregate.mean_score),
        field_accuracy_delta={
            name: _delta(a.aggregate.field_accuracy.get(name), b.aggregate.field_accuracy.get(name))
            for name in fields
        },
        a_source=a.run.source,
        b_source=b.run.source,
    )
