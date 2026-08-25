from decimal import Decimal

import pytest

from agentscope.domain.errors import InvalidStateTransition
from agentscope.domain.models import (
    AgentConfiguration,
    ExperimentRun,
    FaultInjectionPolicy,
    Score,
    TaskId,
)
from agentscope.domain.states import RunStatus


def test_run_follows_explicit_happy_path() -> None:
    run = ExperimentRun(TaskId("task"), AgentConfiguration("mock"))
    for state in (
        RunStatus.QUEUED,
        RunStatus.PROVISIONING,
        RunStatus.RUNNING,
        RunStatus.EVALUATING,
        RunStatus.COMPLETED,
    ):
        run = run.transition(state)
    assert run.status is RunStatus.COMPLETED
    assert run.status.terminal


def test_invalid_transition_fails_loudly() -> None:
    run = ExperimentRun(TaskId("task"), AgentConfiguration("mock"))
    with pytest.raises(InvalidStateTransition, match="created.*completed"):
        run.transition(RunStatus.COMPLETED)


def test_terminal_state_cannot_transition() -> None:
    run = ExperimentRun(TaskId("task"), AgentConfiguration("mock"))
    run = run.transition(RunStatus.CANCELLED)
    with pytest.raises(InvalidStateTransition):
        run.transition(RunStatus.QUEUED)


def test_fault_policy_validates_probabilities() -> None:
    with pytest.raises(ValueError, match="probabilities"):
        FaultInjectionPolicy(tool_failure_probability=1.1)


def test_score_is_exact_decimal_sum() -> None:
    score = Score(Decimal(70), Decimal(15), Decimal(10), Decimal(5))
    assert score.total == Decimal(100)
