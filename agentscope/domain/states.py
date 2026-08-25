from __future__ import annotations

from enum import StrEnum

from agentscope.domain.errors import InvalidStateTransition


class RunStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    PROVISIONING = "provisioning"
    RUNNING = "running"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SANDBOX_FAILED = "sandbox_failed"
    AGENT_FAILED = "agent_failed"
    TIMED_OUT = "timed_out"
    EVALUATION_FAILED = "evaluation_failed"

    @property
    def terminal(self) -> bool:
        return self in TERMINAL_STATUSES


class FailureCategory(StrEnum):
    BUILD_FAILURE = "build_failure"
    TEST_FAILURE = "test_failure"
    TIMEOUT = "timeout"
    TOOL_FAILURE = "tool_failure"
    INVALID_PATCH = "invalid_patch"
    AGENT_ABORTED = "agent_aborted"
    RATE_LIMITED = "rate_limited"
    SANDBOX_FAILURE = "sandbox_failure"
    REGRESSION = "regression"
    CONSTRAINT_VIOLATION = "constraint_violation"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"


TERMINAL_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.CANCELLED,
        RunStatus.SANDBOX_FAILED,
        RunStatus.AGENT_FAILED,
        RunStatus.TIMED_OUT,
        RunStatus.EVALUATION_FAILED,
    }
)

LEGAL_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.QUEUED: frozenset({RunStatus.PROVISIONING, RunStatus.CANCELLED}),
    RunStatus.PROVISIONING: frozenset(
        {RunStatus.RUNNING, RunStatus.SANDBOX_FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.EVALUATING,
            RunStatus.AGENT_FAILED,
            RunStatus.SANDBOX_FAILED,
            RunStatus.TIMED_OUT,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.EVALUATING: frozenset(
        {RunStatus.COMPLETED, RunStatus.EVALUATION_FAILED, RunStatus.TIMED_OUT}
    ),
    **{status: frozenset() for status in TERMINAL_STATUSES},
}


def validate_transition(current: RunStatus, target: RunStatus) -> None:
    """Fail loudly unless *target* is an allowed next state."""
    if target not in LEGAL_TRANSITIONS[current]:
        raise InvalidStateTransition(f"cannot transition run from {current} to {target}")
