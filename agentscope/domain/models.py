from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import NewType
from uuid import uuid4

from agentscope.domain.states import FailureCategory, RunStatus, validate_transition

RunId = NewType("RunId", str)
TaskId = NewType("TaskId", str)
ExperimentId = NewType("ExperimentId", str)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ModelConfiguration:
    provider: str
    model: str
    base_url: str | None = None
    temperature: float = 0.0
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")


@dataclass(frozen=True, slots=True)
class AgentConfiguration:
    name: str
    model: ModelConfiguration | None = None
    tools: tuple[str, ...] = ()
    system_prompt: str = ""
    max_steps: int = 50

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")


@dataclass(frozen=True, slots=True)
class FaultInjectionPolicy:
    seed: int = 0
    tool_failure_probability: float = 0.0
    tool_timeout_probability: float = 0.0
    additional_tool_latency_ms: int = 0

    def __post_init__(self) -> None:
        for value in (self.tool_failure_probability, self.tool_timeout_probability):
            if not 0 <= value <= 1:
                raise ValueError("fault probabilities must be between 0 and 1")
        if self.additional_tool_latency_ms < 0:
            raise ValueError("additional latency cannot be negative")


@dataclass(frozen=True, slots=True)
class EvaluationTask:
    id: TaskId
    name: str
    repository: Path
    description: str
    public_test_command: tuple[str, ...]
    hidden_test_command: tuple[str, ...]
    hidden_tests: Path | None = None
    timeout_seconds: int = 300
    forbidden_paths: tuple[str, ...] = ("tests/",)
    version: str = "1"

    def __post_init__(self) -> None:
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if not self.public_test_command or not self.hidden_test_command:
            raise ValueError("public and hidden test commands are required")


@dataclass(frozen=True, slots=True)
class Score:
    correctness: Decimal
    regression_safety: Decimal
    constraint_adherence: Decimal
    efficiency: Decimal

    @property
    def total(self) -> Decimal:
        return sum(
            (
                self.correctness,
                self.regression_safety,
                self.constraint_adherence,
                self.efficiency,
            ),
            Decimal(0),
        )


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    passed: bool
    public_passed: bool
    hidden_passed: bool
    constraints_satisfied: bool
    score: Score
    duration_seconds: float
    failure_category: FailureCategory | None = None
    details: str = ""


@dataclass(frozen=True, slots=True)
class RunMeasurements:
    agent_duration_seconds: float = 0.0
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    task_id: TaskId
    agent_configuration: AgentConfiguration
    id: RunId = field(default_factory=lambda: RunId(f"run_{uuid4().hex[:12]}"))
    status: RunStatus = RunStatus.CREATED
    seed: int = 0
    task_hash: str = ""
    environment_fingerprint: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    result: EvaluationResult | None = None
    measurements: RunMeasurements = field(default_factory=RunMeasurements)
    failure_message: str | None = None

    def transition(
        self,
        target: RunStatus,
        *,
        result: EvaluationResult | None = None,
        failure_message: str | None = None,
    ) -> ExperimentRun:
        validate_transition(self.status, target)
        return replace(
            self,
            status=target,
            updated_at=utc_now(),
            result=result if result is not None else self.result,
            failure_message=(
                failure_message if failure_message is not None else self.failure_message
            ),
        )


@dataclass(frozen=True, slots=True)
class Experiment:
    name: str
    task_ids: tuple[TaskId, ...]
    configurations: tuple[AgentConfiguration, ...]
    id: ExperimentId = field(default_factory=lambda: ExperimentId(f"exp_{uuid4().hex[:12]}"))
    seed: int = 0

    def __post_init__(self) -> None:
        if not self.task_ids or not self.configurations:
            raise ValueError("experiments require tasks and agent configurations")
