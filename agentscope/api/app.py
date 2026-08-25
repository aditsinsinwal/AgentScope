from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agentscope import __version__
from agentscope.agents.mock import MockAgent
from agentscope.api.schemas import (
    AgentConfigurationSchema,
    ErrorBody,
    ExperimentCreate,
    ExperimentView,
    RunBatchView,
    RunView,
    TaskCreate,
    TaskView,
    TraceView,
)
from agentscope.application.repositories import InMemoryRunRepository
from agentscope.application.run_engine import RunEngine
from agentscope.domain.errors import AgentScopeError, RunNotFoundError
from agentscope.domain.models import (
    AgentConfiguration,
    Experiment,
    ExperimentRun,
    ModelConfiguration,
    RunId,
    TaskId,
)
from agentscope.domain.states import RunStatus
from agentscope.evaluation.evaluator import TestBasedEvaluator
from agentscope.execution.sandbox.docker import DockerSandbox
from agentscope.execution.sandbox.local import LocalSandbox
from agentscope.metrics.aggregate import aggregate_runs
from agentscope.scheduler.local import AsyncRunScheduler, ScheduledJob
from agentscope.tasks.loader import load_task, task_fingerprint
from agentscope.tracing.recorder import InMemoryTraceRecorder
from agentscope.tracing.render import render_trace


def _agent_config(value: AgentConfigurationSchema) -> AgentConfiguration:
    model = ModelConfiguration(**value.model.model_dump()) if value.model else None
    return AgentConfiguration(value.name, model, value.tools, value.system_prompt, value.max_steps)


def _run_view(run: ExperimentRun) -> RunView:
    return RunView(
        id=str(run.id),
        task_id=str(run.task_id),
        agent=run.agent_configuration.name,
        status=run.status.value,
        seed=run.seed,
        task_hash=run.task_hash,
        created_at=run.created_at,
        updated_at=run.updated_at,
        passed=run.result.passed if run.result else None,
        score=run.result.score.total if run.result else None,
        agent_duration_seconds=run.measurements.agent_duration_seconds,
        model_calls=run.measurements.model_calls,
        tool_calls=run.measurements.tool_calls,
        input_tokens=run.measurements.input_tokens,
        output_tokens=run.measurements.output_tokens,
        failure_message=run.failure_message,
    )


class ApiState:
    def __init__(self, sandbox_kind: str) -> None:
        self.sandbox_kind = sandbox_kind
        self.tasks: dict[TaskId, Any] = {}
        self.experiments: dict[str, Experiment] = {}
        self.runs = InMemoryRunRepository()
        self.traces = InMemoryTraceRecorder()
        self.scheduler = AsyncRunScheduler()
        self.run_jobs: dict[RunId, str] = {}

        def factory(task: Any) -> Any:
            if sandbox_kind == "local":
                return LocalSandbox(task.repository, task.hidden_tests)
            return DockerSandbox(task.repository, task.hidden_tests)

        self.engine = RunEngine(self.runs, self.traces, TestBasedEvaluator(), factory)


def create_app(*, sandbox_kind: str = "docker", serve_frontend: bool = True) -> FastAPI:
    state = ApiState(sandbox_kind)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> Any:
        await state.scheduler.start()
        yield
        await state.scheduler.close()

    app = FastAPI(title="AgentScope API", version="0.1.0", lifespan=lifespan)
    app.state.services = state

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "sandbox": state.sandbox_kind}

    @app.exception_handler(AgentScopeError)
    async def expected_error(_: Request, exc: AgentScopeError) -> JSONResponse:
        code = "not_found" if isinstance(exc, RunNotFoundError) else "agentscope_error"
        http_status = status.HTTP_404_NOT_FOUND if code == "not_found" else 422
        return JSONResponse(
            status_code=http_status,
            content=ErrorBody(code=code, message=str(exc)).model_dump(),
        )

    @app.post("/api/v1/tasks", response_model=TaskView, status_code=201)
    async def create_task(body: TaskCreate) -> TaskView:
        task = load_task(Path(body.definition_path))
        state.tasks[task.id] = task
        return TaskView(
            id=str(task.id),
            name=task.name,
            description=task.description,
            version=task.version,
            fingerprint=task_fingerprint(task),
        )

    @app.get("/api/v1/tasks", response_model=list[TaskView])
    async def list_tasks(
        offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200)
    ) -> list[TaskView]:
        tasks = list(state.tasks.values())[offset : offset + limit]
        return [
            TaskView(
                id=str(task.id),
                name=task.name,
                description=task.description,
                version=task.version,
                fingerprint=task_fingerprint(task),
            )
            for task in tasks
        ]

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskView)
    async def get_task(task_id: str) -> TaskView:
        task = state.tasks.get(TaskId(task_id))
        if task is None:
            raise RunNotFoundError(task_id)
        return TaskView(
            id=task_id,
            name=task.name,
            description=task.description,
            version=task.version,
            fingerprint=task_fingerprint(task),
        )

    @app.post("/api/v1/experiments", response_model=ExperimentView, status_code=201)
    async def create_experiment(body: ExperimentCreate) -> ExperimentView:
        missing = [task_id for task_id in body.task_ids if TaskId(task_id) not in state.tasks]
        if missing:
            raise RunNotFoundError(f"unknown tasks: {', '.join(missing)}")
        experiment = Experiment(
            body.name,
            tuple(TaskId(value) for value in body.task_ids),
            tuple(_agent_config(value) for value in body.configurations),
            seed=body.seed,
        )
        state.experiments[str(experiment.id)] = experiment
        return ExperimentView(
            id=str(experiment.id),
            name=experiment.name,
            task_ids=tuple(str(value) for value in experiment.task_ids),
            configuration_names=tuple(value.name for value in experiment.configurations),
            seed=experiment.seed,
        )

    @app.get("/api/v1/experiments/{experiment_id}", response_model=ExperimentView)
    async def get_experiment(experiment_id: str) -> ExperimentView:
        experiment = state.experiments.get(experiment_id)
        if experiment is None:
            raise RunNotFoundError(experiment_id)
        return ExperimentView(
            id=experiment_id,
            name=experiment.name,
            task_ids=tuple(str(value) for value in experiment.task_ids),
            configuration_names=tuple(value.name for value in experiment.configurations),
            seed=experiment.seed,
        )

    @app.post(
        "/api/v1/experiments/{experiment_id}/run", response_model=RunBatchView, status_code=202
    )
    async def run_experiment(experiment_id: str) -> RunBatchView:
        experiment = state.experiments.get(experiment_id)
        if experiment is None:
            raise RunNotFoundError(experiment_id)
        ids: list[str] = []
        for task_id in experiment.task_ids:
            for configuration in experiment.configurations:
                run = ExperimentRun(task_id, configuration, seed=experiment.seed)
                await state.runs.save(run)
                task = state.tasks[task_id]

                async def execute_run(run: ExperimentRun = run, task: Any = task) -> ExperimentRun:
                    return await state.engine.execute(run, task, MockAgent(()))

                job = ScheduledJob(execute_run)
                future = await state.scheduler.submit(job)
                future.add_done_callback(
                    lambda done: None if done.cancelled() else done.exception()
                )
                state.run_jobs[run.id] = job.id
                ids.append(str(run.id))
        return RunBatchView(run_ids=tuple(ids))

    @app.get("/api/v1/runs/{run_id}", response_model=RunView)
    async def get_run(run_id: str) -> RunView:
        return _run_view(await state.runs.get(RunId(run_id)))

    @app.get("/api/v1/runs", response_model=list[RunView])
    async def list_runs(
        offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200)
    ) -> list[RunView]:
        return [_run_view(run) for run in await state.runs.list(offset, limit)]

    @app.get("/api/v1/runs/{run_id}/trace", response_model=TraceView)
    async def get_trace(run_id: str, from_step: int = Query(default=1, ge=1)) -> TraceView:
        await state.runs.get(RunId(run_id))
        events = await state.traces.events(RunId(run_id))
        return TraceView(run_id=run_id, timeline=render_trace(events, from_step))

    @app.get("/api/v1/runs/{run_id}/metrics")
    async def get_metrics(run_id: str) -> dict[str, Any]:
        run = await state.runs.get(RunId(run_id))
        metrics = aggregate_runs([run])
        return {
            "solve_rate": metrics.solve_rate,
            "hidden_test_pass_rate": metrics.hidden_test_pass_rate,
            "average_score": str(metrics.average_score),
            "model_calls": run.measurements.model_calls,
            "tool_calls": run.measurements.tool_calls,
            "input_tokens": run.measurements.input_tokens,
            "output_tokens": run.measurements.output_tokens,
        }

    @app.get("/api/v1/experiments/{experiment_id}/results")
    async def experiment_results(experiment_id: str) -> dict[str, Any]:
        if experiment_id not in state.experiments:
            raise RunNotFoundError(experiment_id)
        # In-memory records do not currently persist experiment_id; select its task/config matrix.
        experiment = state.experiments[experiment_id]
        all_runs = await state.runs.list(0, 10_000)
        runs = [
            run
            for run in all_runs
            if run.task_id in experiment.task_ids
            and run.agent_configuration in experiment.configurations
            and run.seed == experiment.seed
        ]
        metrics = aggregate_runs(runs)
        return {
            "run_count": metrics.run_count,
            "completed_count": metrics.completed_count,
            "solve_rate": metrics.solve_rate,
            "average_score": str(metrics.average_score),
            "average_model_calls": metrics.average_model_calls,
            "average_tool_calls": metrics.average_tool_calls,
            "total_input_tokens": metrics.total_input_tokens,
            "total_output_tokens": metrics.total_output_tokens,
            "warning": "No statistical-significance claim is made.",
        }

    @app.post("/api/v1/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(run_id: str) -> RunView:
        run = await state.runs.get(RunId(run_id))
        job_id = state.run_jobs.get(run.id)
        if job_id and state.scheduler.cancel(job_id) and not run.status.terminal:
            run = run.transition(RunStatus.CANCELLED)
            await state.runs.save(run)
        return _run_view(run)

    static_directory = Path(__file__).with_name("static")
    if serve_frontend and (static_directory / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_directory, html=True), name="dashboard")

    return app


app = create_app()
