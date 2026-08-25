from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from agentscope.agents.base import Agent
from agentscope.application.run_engine import RunEngine
from agentscope.domain.models import EvaluationTask, Experiment, ExperimentRun, TaskId

AgentFactory = Callable[[object], Agent]


class ExperimentEngine:
    """Creates the fair task-by-configuration matrix with shared experiment seed."""

    def __init__(self, run_engine: RunEngine, agent_factory: AgentFactory) -> None:
        self.run_engine = run_engine
        self.agent_factory = agent_factory

    def plan(
        self, experiment: Experiment, tasks: Mapping[TaskId, EvaluationTask]
    ) -> Sequence[tuple[ExperimentRun, EvaluationTask, Agent]]:
        planned: list[tuple[ExperimentRun, EvaluationTask, Agent]] = []
        for task_id in experiment.task_ids:
            task = tasks[task_id]
            for configuration in experiment.configurations:
                run = ExperimentRun(task_id, configuration, seed=experiment.seed)
                planned.append((run, task, self.agent_factory(configuration)))
        return tuple(planned)

    async def execute(
        self, experiment: Experiment, tasks: Mapping[TaskId, EvaluationTask]
    ) -> Sequence[ExperimentRun]:
        # Concurrency is deliberately delegated to AsyncRunScheduler in production.
        results: list[ExperimentRun] = []
        for run, task, agent in self.plan(experiment, tasks):
            results.append(await self.run_engine.execute(run, task, agent))
        return tuple(results)
