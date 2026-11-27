"""Paired statistics for suite comparison. Pure standard library, deterministic per seed.

Nothing here decides anything: it returns an interval or a p-value with its method, and the
caller reports the numbers.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

DEFAULT_RESAMPLES = 10_000
DEFAULT_CONFIDENCE = 0.95
DEFAULT_SEED = 0
MIN_RESAMPLES = 100
MAX_RESAMPLES = 100_000
API_MAX_RESAMPLES = 20_000
# Upper bound on resamples * paired cases * metrics, which sets the bootstrap's CPU cost.
MAX_BOOTSTRAP_WORK = 20_000_000
MAX_SEED = 2**63
BOOTSTRAP_METHOD = "paired percentile bootstrap"
MCNEMAR_METHOD = "exact two-sided binomial"


@dataclass(frozen=True, slots=True)
class Interval:
    estimate: float
    low: float
    high: float
    n: int


def validate_params(resamples: int, confidence: float) -> None:
    if not MIN_RESAMPLES <= resamples <= MAX_RESAMPLES:
        raise ValueError(f"resamples must be between {MIN_RESAMPLES} and {MAX_RESAMPLES}")
    if not 0.5 < confidence < 1:
        raise ValueError("confidence must be greater than 0.5 and less than 1")


def check_work_budget(resamples: int, n_cases: int, n_metrics: int) -> None:
    work = resamples * n_cases * n_metrics
    if work > MAX_BOOTSTRAP_WORK:
        raise ValueError(
            f"bootstrap work {resamples} resamples x {n_cases} paired cases x {n_metrics} metrics "
            f"= {work} exceeds the limit of {MAX_BOOTSTRAP_WORK}; lower the resamples"
        )


def quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile of an already sorted sequence."""
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def paired_bootstrap(
    metrics: Mapping[str, Sequence[float | None]],
    *,
    resamples: int = DEFAULT_RESAMPLES,
    confidence: float = DEFAULT_CONFIDENCE,
    seed: int = DEFAULT_SEED,
) -> dict[str, Interval | None]:
    """Percentile bootstrap of the mean paired difference for each named metric.

    Every metric is a list with one entry per paired case, in a fixed (caller-sorted) order;
    ``None`` marks a case that does not contribute to that metric. All metrics share the same
    resampled case indices in each round. A metric with fewer than 2 contributing cases maps
    to ``None``. A round where a metric has no contributing case is skipped for that metric.
    """
    validate_params(resamples, confidence)
    lengths = {len(v) for v in metrics.values()}
    if len(lengths) > 1:
        raise ValueError("all metrics must cover the same paired cases")
    n = lengths.pop() if lengths else 0
    values: dict[str, list[float]] = {}
    present: dict[str, list[int]] = {}
    out: dict[str, Interval | None] = {}
    for name, series in metrics.items():
        used = [x for x in series if x is not None]
        if len(used) < 2:
            out[name] = None
            continue
        values[name] = [0.0 if x is None else float(x) for x in series]
        present[name] = [0 if x is None else 1 for x in series]
    if not values:
        return out
    check_work_budget(resamples, n, len(values))
    rng = random.Random(seed)
    population = range(n)
    draws: dict[str, list[float]] = {name: [] for name in values}
    for _ in range(resamples):
        idx = rng.choices(population, k=n)
        for name, vals in values.items():
            mask = present[name]
            count = sum(map(mask.__getitem__, idx))
            if count:
                draws[name].append(sum(map(vals.__getitem__, idx)) / count)
    alpha = (1 - confidence) / 2
    for name, vals in values.items():
        mask = present[name]
        count = sum(mask)
        estimate = sum(vals) / count
        ordered = sorted(draws[name])
        out[name] = Interval(
            estimate=estimate,
            low=quantile(ordered, alpha),
            high=quantile(ordered, 1 - alpha),
            n=count,
        )
    return out


def mcnemar_exact(b_only: int, a_only: int) -> float:
    """Exact two-sided McNemar p-value on the discordant pairs (1.0 when there are none)."""
    n = b_only + a_only
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b_only, a_only) + 1))
    return float(min(1.0, 2 * tail / 2**n))
