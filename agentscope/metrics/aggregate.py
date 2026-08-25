from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal

from agentscope.domain.models import ExperimentRun
from agentscope.domain.states import FailureCategory, RunStatus


@dataclass(frozen=True, slots=True)
class ExperimentMetrics:
    run_count: int
    completed_count: int
    solve_rate: float
    hidden_test_pass_rate: float
    average_score: Decimal
    median_evaluation_seconds: float
    p95_evaluation_seconds: float
    average_model_calls: float
    average_tool_calls: float
    total_input_tokens: int
    total_output_tokens: int
    failure_counts: dict[FailureCategory, int]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def aggregate_runs(runs: list[ExperimentRun]) -> ExperimentMetrics:
    results = [run.result for run in runs if run.result is not None]
    scores = [result.score.total for result in results]
    durations = [result.duration_seconds for result in results]
    failures: dict[FailureCategory, int] = {}
    for result in results:
        if result.failure_category:
            failures[result.failure_category] = failures.get(result.failure_category, 0) + 1
    count = len(runs)
    return ExperimentMetrics(
        count,
        sum(run.status is RunStatus.COMPLETED for run in runs),
        sum(result.passed for result in results) / count if count else 0.0,
        sum(result.hidden_passed for result in results) / count if count else 0.0,
        sum(scores, Decimal(0)) / len(scores) if scores else Decimal(0),
        statistics.median(durations) if durations else 0.0,
        _percentile(durations, 0.95),
        sum(run.measurements.model_calls for run in runs) / count if count else 0.0,
        sum(run.measurements.tool_calls for run in runs) / count if count else 0.0,
        sum(run.measurements.input_tokens for run in runs),
        sum(run.measurements.output_tokens for run in runs),
        failures,
    )
