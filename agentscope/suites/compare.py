"""Paired comparison of two results.json documents. Counts only; no significance claims."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentscope.domain.errors import SuiteComparisonError
from agentscope.suites.results import ResultsDocument
from agentscope.suites.stats import (
    BOOTSTRAP_METHOD,
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    MCNEMAR_METHOD,
    Interval,
    mcnemar_exact,
    paired_bootstrap,
)

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
    # Paired bootstrap intervals and McNemar test over the paired cases (B minus A).
    intervals: dict[str, Any] = field(default_factory=dict)


def _delta(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else b - a


def _interval(value: Interval | None, *, with_n: bool = False) -> dict[str, Any] | None:
    if value is None:
        return None
    body: dict[str, Any] = {"estimate": value.estimate, "low": value.low, "high": value.high}
    if with_n:
        body["n"] = value.n
    return body


def compare_results(
    a: ResultsDocument,
    b: ResultsDocument,
    *,
    allow_mismatch: bool = False,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = DEFAULT_SEED,
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
    score_d: list[float | None] = []
    pass_d: list[float | None] = []
    fmt_d: list[float | None] = []
    field_d: dict[str, list[float | None]] = {}
    pairs = []
    for case_id in sorted(set(by_a) | set(by_b)):
        ca, cb = by_a.get(case_id), by_b.get(case_id)
        if not (ca and cb and ca.check and cb.check):
            unpaired += 1
            continue
        fmt_b += cb.check.format_valid and not ca.check.format_valid
        fmt_a += ca.check.format_valid and not cb.check.format_valid
        pass_b += cb.check.passed and not ca.check.passed
        pass_a += ca.check.passed and not cb.check.passed
        pairs.append((ca.check, cb.check))
        diff = cb.check.score - ca.check.score
        if diff > _EPS:
            better_b += 1
        elif diff < -_EPS:
            better_a += 1
        else:
            tie += 1
    field_names = sorted(
        {n for ca_, cb_ in pairs for n in (ca_.fields or {}).keys() | (cb_.fields or {}).keys()}
    )
    for ca_, cb_ in pairs:
        score_d.append(cb_.score - ca_.score)
        pass_d.append(float(cb_.passed) - float(ca_.passed))
        fmt_d.append(float(cb_.format_valid) - float(ca_.format_valid))
        for name in field_names:
            fa = (ca_.fields or {}).get(name)
            fb = (cb_.fields or {}).get(name)
            usable = fa and fb and fa.matched is not None and fb.matched is not None
            field_d.setdefault(name, []).append(
                float(bool(fb.matched)) - float(bool(fa.matched)) if usable and fa and fb else None
            )
    metrics: dict[str, list[float | None]] = {
        "mean_score_delta": score_d,
        "pass_rate_delta": pass_d,
        "format_valid_rate_delta": fmt_d,
    }
    metrics.update({f"field:{name}": series for name, series in field_d.items()})
    boot = paired_bootstrap(metrics, resamples=resamples, confidence=confidence, seed=seed)
    n_pairs = len(pairs)
    intervals: dict[str, Any] = {
        "method": BOOTSTRAP_METHOD,
        "resamples": resamples,
        "confidence": confidence,
        "seed": seed,
        "n_paired": n_pairs,
        "mean_score_delta": _interval(boot["mean_score_delta"]),
        "pass_rate_delta": _interval(boot["pass_rate_delta"]),
        "format_valid_rate_delta": _interval(boot["format_valid_rate_delta"]),
        "field_accuracy_delta": {
            name: _interval(boot[f"field:{name}"], with_n=True) for name in field_names
        },
        "mcnemar_pass": (
            {
                "b_only": pass_b,
                "a_only": pass_a,
                "p_value": mcnemar_exact(pass_b, pass_a),
                "method": MCNEMAR_METHOD,
            }
            if n_pairs >= 2
            else None
        ),
    }
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
        intervals=intervals,
    )
