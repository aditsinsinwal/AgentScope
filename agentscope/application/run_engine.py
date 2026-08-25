from __future__ import annotations

import asyncio
import platform
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from agentscope.agents.base import Agent, ToolEnvironment
from agentscope.application.repositories import RunRepository
from agentscope.domain.errors import AgentExecutionError, EvaluationError, SandboxError
from agentscope.domain.models import (
    EvaluationTask,
    ExperimentRun,
    FaultInjectionPolicy,
    RunMeasurements,
)
from agentscope.domain.states import RunStatus
from agentscope.evaluation.base import Evaluator
from agentscope.execution.sandbox.base import Sandbox
from agentscope.execution.tools.registry import default_tool_registry
from agentscope.reliability.faults import FaultInjectingEnvironment
from agentscope.tasks.loader import task_fingerprint
from agentscope.tracing.models import EventType, TraceEvent
from agentscope.tracing.recorder import TraceRecorder

SandboxFactory = Callable[[EvaluationTask], AbstractAsyncContextManager[Sandbox]]


class RunEngine:
    def __init__(
        self,
        runs: RunRepository,
        traces: TraceRecorder,
        evaluator: Evaluator,
        sandbox_factory: SandboxFactory,
    ) -> None:
        self.runs = runs
        self.traces = traces
        self.evaluator = evaluator
        self.sandbox_factory = sandbox_factory

    async def _transition(self, run: ExperimentRun, status: RunStatus) -> ExperimentRun:
        run = run.transition(status)
        await self.runs.save(run)
        await self.traces.append(
            TraceEvent(run.id, 0, EventType.RUN_STATE, status.value, output_summary=status.value)
        )
        return run

    async def execute(
        self,
        run: ExperimentRun,
        task: EvaluationTask,
        agent: Agent,
        faults: FaultInjectionPolicy | None = None,
    ) -> ExperimentRun:
        if run.status is RunStatus.CREATED:
            await self.runs.save(run)
            run = await self._transition(run, RunStatus.QUEUED)
        run = await self._transition(run, RunStatus.PROVISIONING)
        try:
            with TemporaryDirectory(prefix="agentscope-frozen-") as temporary:
                frozen = Path(temporary) / "workspace"
                async with self.sandbox_factory(task) as sandbox:
                    run = await self._transition(run, RunStatus.RUNNING)
                    before = await sandbox.snapshot_hashes(task.forbidden_paths)
                    registry = default_tool_registry(sandbox, self.traces, run.id)
                    environment: ToolEnvironment | FaultInjectingEnvironment = ToolEnvironment(
                        registry
                    )
                    if faults is not None:
                        environment = FaultInjectingEnvironment(environment, faults)
                    agent_started = time.monotonic()
                    try:
                        agent_result = await asyncio.wait_for(
                            agent.run(task, environment), task.timeout_seconds
                        )
                    except TimeoutError:
                        return await self._transition(run, RunStatus.TIMED_OUT)
                    except AgentExecutionError as exc:
                        failed = run.transition(RunStatus.AGENT_FAILED, failure_message=str(exc))
                        await self.runs.save(failed)
                        return failed
                    if not agent_result.completed:
                        failed = run.transition(
                            RunStatus.AGENT_FAILED, failure_message=agent_result.message
                        )
                        await self.runs.save(failed)
                        return failed
                    run = replace(
                        run,
                        measurements=RunMeasurements(
                            agent_duration_seconds=time.monotonic() - agent_started,
                            model_calls=agent_result.usage.model_calls,
                            tool_calls=agent_result.tool_calls,
                            input_tokens=agent_result.usage.input_tokens,
                            output_tokens=agent_result.usage.output_tokens,
                            cached_tokens=agent_result.usage.cached_tokens,
                        ),
                    )
                    await sandbox.export_workspace(frozen)
                run = await self._transition(run, RunStatus.EVALUATING)
                evaluation_task = replace(task, repository=frozen)
                try:
                    async with self.sandbox_factory(evaluation_task) as evaluation_sandbox:
                        result = await self.evaluator.evaluate(
                            evaluation_task, evaluation_sandbox, before
                        )
                except SandboxError:
                    raise
                except Exception as exc:
                    raise EvaluationError(str(exc)) from exc
                completed = run.transition(RunStatus.COMPLETED, result=result)
                completed = ExperimentRun(
                    task_id=completed.task_id,
                    agent_configuration=completed.agent_configuration,
                    id=completed.id,
                    status=completed.status,
                    seed=completed.seed,
                    task_hash=task_fingerprint(task),
                    environment_fingerprint=f"python-{platform.python_version()}",
                    created_at=completed.created_at,
                    updated_at=completed.updated_at,
                    result=completed.result,
                    measurements=completed.measurements,
                )
                await self.runs.save(completed)
                await self.traces.append(
                    TraceEvent(
                        run.id,
                        0,
                        EventType.EVALUATION,
                        "deterministic_tests",
                        status="pass" if result.passed else "fail",
                        output_summary=f"score={result.score.total}",
                    )
                )
                await self.traces.append(
                    TraceEvent(
                        run.id,
                        0,
                        EventType.RUN_STATE,
                        RunStatus.COMPLETED.value,
                        output_summary=RunStatus.COMPLETED.value,
                    )
                )
                return completed
        except SandboxError as exc:
            target = (
                RunStatus.EVALUATION_FAILED
                if run.status is RunStatus.EVALUATING
                else RunStatus.SANDBOX_FAILED
            )
            failed = run.transition(target, failure_message=str(exc))
            await self.runs.save(failed)
            return failed
        except EvaluationError as exc:
            failed = run.transition(RunStatus.EVALUATION_FAILED, failure_message=str(exc))
            await self.runs.save(failed)
            return failed
