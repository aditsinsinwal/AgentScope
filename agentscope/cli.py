from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from agentscope.agents.mock import MockAction, MockAgent
from agentscope.api.app import create_app
from agentscope.application.repositories import InMemoryRunRepository
from agentscope.application.run_engine import RunEngine
from agentscope.config import get_settings
from agentscope.domain.models import AgentConfiguration, EvaluationTask, ExperimentRun, RunId
from agentscope.evaluation.evaluator import TestBasedEvaluator
from agentscope.execution.sandbox.docker import DockerSandbox
from agentscope.execution.sandbox.local import LocalSandbox
from agentscope.replay.service import ReplayService
from agentscope.tasks.loader import load_task
from agentscope.tracing.recorder import JsonlTraceRecorder
from agentscope.tracing.render import render_trace

app = typer.Typer(no_args_is_help=True, help="Evaluate how AI agents behave, fail, and recover.")


@app.command()
def run(
    task_path: Annotated[Path, typer.Option("--task", exists=True, dir_okay=False)],
    agent: Annotated[str, typer.Option("--agent")] = "mock",
    sandbox: Annotated[str, typer.Option("--sandbox")] = "docker",
    mock_actions: Annotated[Path | None, typer.Option("--mock-actions")] = None,
) -> None:
    """Run one task and print the measured result."""
    if agent != "mock":
        raise typer.BadParameter(
            "CLI currently accepts mock; use the Python API for real providers"
        )
    if sandbox not in {"docker", "local"}:
        raise typer.BadParameter("sandbox must be docker or local")

    async def execute() -> None:
        task = load_task(task_path)
        raw = json.loads(mock_actions.read_text()) if mock_actions else []
        actions = tuple(MockAction(item["tool"], item.get("arguments", {})) for item in raw)
        configured = AgentConfiguration("mock", tools=tuple(action.tool for action in actions))
        run = ExperimentRun(task.id, configured)
        traces = JsonlTraceRecorder(get_settings().artifact_root / "traces")

        def factory(run_task: EvaluationTask) -> LocalSandbox | DockerSandbox:
            if sandbox == "local":
                return LocalSandbox(run_task.repository, run_task.hidden_tests)
            return DockerSandbox(run_task.repository, run_task.hidden_tests)

        engine = RunEngine(InMemoryRunRepository(), traces, TestBasedEvaluator(), factory)
        result = await engine.execute(run, task, MockAgent(actions))
        typer.echo(f"Run ID: {result.id}")
        typer.echo(f"Status: {result.status.value}")
        if result.result:
            typer.echo(f"Evaluation: {'PASS' if result.result.passed else 'FAIL'}")
            typer.echo(f"Score: {result.result.score.total} / 100")
            typer.echo(f"Evaluation duration: {result.result.duration_seconds:.3f}s")
        typer.echo(f"Model calls: {result.measurements.model_calls}")
        typer.echo(f"Tool calls: {result.measurements.tool_calls}")
        typer.echo(
            f"Tokens: {result.measurements.input_tokens} input / "
            f"{result.measurements.output_tokens} output"
        )
        if result.failure_message:
            typer.echo(f"Failure: {result.failure_message}")
        typer.echo("\n" + render_trace(await traces.events(result.id)))

    asyncio.run(execute())


@app.command()
def replay(
    run_id: str,
    from_step: Annotated[int, typer.Option("--from-step", min=1)] = 1,
) -> None:
    """Print a stored local execution timeline without re-calling a model."""

    async def execute() -> None:
        service = ReplayService(JsonlTraceRecorder(get_settings().artifact_root / "traces"))
        timeline = await service.replay(RunId(run_id), from_step)
        if not timeline:
            raise typer.BadParameter(f"no local trace found for {run_id}")
        typer.echo(timeline)

    asyncio.run(execute())


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    sandbox: str = "docker",
) -> None:
    """Serve the versioned HTTP API."""
    import uvicorn

    uvicorn.run(create_app(sandbox_kind=sandbox), host=host, port=port)


if __name__ == "__main__":
    app()
