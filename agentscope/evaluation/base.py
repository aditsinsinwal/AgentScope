from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from agentscope.domain.models import EvaluationResult, EvaluationTask
from agentscope.execution.sandbox.base import Sandbox


class Evaluator(Protocol):
    async def evaluate(
        self,
        task: EvaluationTask,
        sandbox: Sandbox,
        forbidden_before: Mapping[str, str],
    ) -> EvaluationResult: ...
