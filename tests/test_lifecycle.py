from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentscope.agents.base import AgentEnvironment, AgentResult
from agentscope.api.app import create_app
from agentscope.application.repositories import InMemoryRunRepository
from agentscope.application.run_engine import RunEngine
from agentscope.domain.models import AgentConfiguration, EvaluationTask, ExperimentRun
from agentscope.domain.states import RunStatus
from agentscope.evaluation.evaluator import TestBasedEvaluator
from agentscope.execution.sandbox.local import LocalSandbox
from agentscope.tasks.loader import load_task
from agentscope.tracing.recorder import InMemoryTraceRecorder

ROOT = Path(__file__).parents[1]


class HangingAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, task: EvaluationTask, environment: AgentEnvironment) -> AgentResult:
        self.started.set()
        await asyncio.sleep(60)
        raise AssertionError("unreachable")


class TrackingSandbox(LocalSandbox):
    entered = 0
    exited = 0

    async def __aenter__(self) -> TrackingSandbox:
        await super().__aenter__()
        type(self).entered += 1
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await super().__aexit__(*exc_info)
        type(self).exited += 1


async def test_cancelling_a_run_unwinds_sandbox_and_records_cancelled() -> None:
    TrackingSandbox.entered = TrackingSandbox.exited = 0
    task = load_task(ROOT / "examples/cart-empty-500/task.yaml")
    runs = InMemoryRunRepository()
    engine = RunEngine(
        runs,
        InMemoryTraceRecorder(),
        TestBasedEvaluator(),
        lambda t: TrackingSandbox(t.repository, t.hidden_tests),
    )
    agent = HangingAgent()
    run = ExperimentRun(task.id, AgentConfiguration("hang"))
    job = asyncio.create_task(engine.execute(run, task, agent))
    await asyncio.wait_for(agent.started.wait(), 5)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert (TrackingSandbox.entered, TrackingSandbox.exited) == (1, 1)
    assert (await runs.get(run.id)).status is RunStatus.CANCELLED


def test_api_cancel_and_shutdown_leave_no_running_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    import agentscope.api.app as api_module

    started = asyncio.Event()
    state: dict[str, Any] = {}

    class SlowAgent(HangingAgent):
        def __init__(self, _: object = None) -> None:
            self.started = started

    monkeypatch.setattr(api_module, "MockAgent", SlowAgent)
    app = create_app(sandbox_kind="local", serve_frontend=False)
    with TestClient(app) as client:
        client.post(
            "/api/v1/tasks",
            json={"definition_path": str(ROOT / "examples/cart-empty-500/task.yaml")},
        )
        experiment = client.post(
            "/api/v1/experiments",
            json={
                "name": "x",
                "task_ids": ["cart-empty-500"],
                "configurations": [{"name": "a"}, {"name": "b"}, {"name": "c"}],
            },
        ).json()
        run_ids = client.post(f"/api/v1/experiments/{experiment['id']}/run").json()["run_ids"]
        scheduler = app.state.services.scheduler
        state["workers"] = list(scheduler._workers)
        cancelled = client.post(f"/api/v1/runs/{run_ids[0]}/cancel")
        assert cancelled.status_code == 202
        assert client.get(f"/api/v1/runs/{run_ids[0]}").json()["status"] == "cancelled"
        # Cancelling again is a harmless no-op, not an error.
        assert client.post(f"/api/v1/runs/{run_ids[0]}/cancel").status_code == 202
    assert all(worker.done() for worker in state["workers"])


async def test_local_sandbox_cancelled_mid_copy_leaves_no_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil
    import threading

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("x")
    entered, release = threading.Event(), threading.Event()
    real = shutil.copytree

    def slow_copy(src: Path, dst: Path) -> Path:
        entered.set()
        release.wait(5)
        return real(src, dst)

    monkeypatch.setattr(shutil, "copytree", slow_copy)
    sandbox = LocalSandbox(repo)
    task = asyncio.create_task(sandbox.__aenter__())
    await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sandbox._temporary is None and sandbox.root is None
