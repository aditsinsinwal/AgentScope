from __future__ import annotations

import time
from collections.abc import Mapping
from decimal import Decimal

from agentscope.domain.models import EvaluationResult, EvaluationTask, Score
from agentscope.domain.states import FailureCategory
from agentscope.execution.sandbox.base import CommandResult, Sandbox


def _command_details(label: str, result: CommandResult) -> str:
    return (
        f"{label}: exit={result.exit_code} timed_out={result.timed_out}\n"
        f"stdout:\n{result.stdout[-5000:]}\nstderr:\n{result.stderr[-5000:]}"
    )


class TestBasedEvaluator:
    """Deterministic evaluator; another LLM is never used as a judge."""

    async def evaluate(
        self,
        task: EvaluationTask,
        sandbox: Sandbox,
        forbidden_before: Mapping[str, str],
    ) -> EvaluationResult:
        started = time.monotonic()
        public = await sandbox.execute(task.public_test_command, task.timeout_seconds)
        forbidden_after = await sandbox.snapshot_hashes(task.forbidden_paths)
        constraints = dict(forbidden_before) == forbidden_after
        await sandbox.install_hidden_tests()
        remaining = max(1.0, task.timeout_seconds - (time.monotonic() - started))
        hidden = await sandbox.execute(task.hidden_test_command, remaining)
        duration = time.monotonic() - started
        public_passed = public.exit_code == 0 and not public.timed_out
        hidden_passed = hidden.exit_code == 0 and not hidden.timed_out
        passed = public_passed and hidden_passed and constraints
        score = Score(
            correctness=Decimal(70 if hidden_passed else 0),
            regression_safety=Decimal(15 if public_passed else 0),
            constraint_adherence=Decimal(10 if constraints else 0),
            efficiency=Decimal(5 if duration <= task.timeout_seconds else 0),
        )
        failure: FailureCategory | None = None
        if public.timed_out or hidden.timed_out:
            failure = FailureCategory.TIMEOUT
        elif not constraints:
            failure = FailureCategory.CONSTRAINT_VIOLATION
        elif not public_passed:
            failure = FailureCategory.REGRESSION
        elif not hidden_passed:
            failure = FailureCategory.TEST_FAILURE
        return EvaluationResult(
            passed,
            public_passed,
            hidden_passed,
            constraints,
            score,
            duration,
            failure,
            _command_details("public", public) + "\n" + _command_details("hidden", hidden),
        )
