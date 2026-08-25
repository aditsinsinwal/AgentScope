"""Dependency-free core domain."""

from agentscope.domain.models import (
    AgentConfiguration,
    EvaluationResult,
    EvaluationTask,
    Experiment,
    ExperimentRun,
    FaultInjectionPolicy,
    ModelConfiguration,
    RunMeasurements,
    Score,
)
from agentscope.domain.states import FailureCategory, RunStatus

__all__ = [
    "AgentConfiguration",
    "EvaluationResult",
    "EvaluationTask",
    "Experiment",
    "ExperimentRun",
    "FailureCategory",
    "FaultInjectionPolicy",
    "ModelConfiguration",
    "RunMeasurements",
    "RunStatus",
    "Score",
]
