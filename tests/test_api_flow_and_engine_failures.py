from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agentscope.agents.base import AgentEnvironment, AgentResult
from agentscope.agents.mock import MockAction, MockAgent
from agentscope.api.app import create_app
from agentscope.application.repositories import InMemoryRunRepository
from agentscope.application.run_engine import RunEngine
from agentscope.domain.errors import AgentLimitExceeded, ProviderError
from agentscope.domain.models import AgentConfiguration, EvaluationTask, ExperimentRun
from agentscope.domain.states import RunStatus
from agentscope.evaluation.evaluator import TestBasedEvaluator
from agentscope.execution.sandbox.local import LocalSandbox
from agentscope.tasks.loader import load_task
from agentscope.tracing.recorder import InMemoryTraceRecorder

ROOT = Path(__file__).parents[1]
TASK = ROOT / "examples/cart-empty-500/task.yaml"


def _engine() -> RunEngine:
    return RunEngine(
        InMemoryRunRepository(),
        InMemoryTraceRecorder(),
        TestBasedEvaluator(),
        lambda t: LocalSandbox(t.repository, t.hidden_tests),
    )


class Raising:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def run(self, task: EvaluationTask, environment: AgentEnvironment) -> AgentResult:
        raise self.error


async def test_provider_failure_and_limit_are_distinct_agent_failed_outcomes() -> None:
    task = load_task(TASK)
    engine = _engine()
    limited = await engine.execute(
        ExperimentRun(task.id, AgentConfiguration("a")),
        task,
        Raising(AgentLimitExceeded("max_steps", 3)),
    )
    failed = await engine.execute(
        ExperimentRun(task.id, AgentConfiguration("b")),
        task,
        Raising(ProviderError("provider server error (HTTP 503)", retryable=True, status_code=503)),
    )
    assert limited.status is failed.status is RunStatus.AGENT_FAILED
    assert (limited.failure_message or "").startswith("limit_exceeded:")
    assert "HTTP 503" in (failed.failure_message or "")


async def test_incomplete_agent_result_marks_agent_failed() -> None:
    task = load_task(TASK)
    run = await _engine().execute(
        ExperimentRun(task.id, AgentConfiguration("m")),
        task,
        MockAgent((MockAction("read_file", {"path": "missing.py"}),)),
    )
    assert run.status is RunStatus.AGENT_FAILED


def test_full_api_flow_trace_metrics_results_and_listing() -> None:
    with TestClient(create_app(sandbox_kind="local", serve_frontend=False)) as client:
        assert client.post("/api/v1/tasks", json={"definition_path": str(TASK)}).status_code == 201
        assert client.get("/api/v1/tasks").json()[0]["id"] == "cart-empty-500"
        assert client.get("/api/v1/tasks/cart-empty-500").status_code == 200
        assert client.get("/api/v1/tasks/unknown").status_code == 404
        experiment: dict[str, Any] = client.post(
            "/api/v1/experiments",
            json={
                "name": "e",
                "task_ids": ["cart-empty-500"],
                "configurations": [{"name": "mock"}],
                "seed": 1,
            },
        ).json()
        assert client.get(f"/api/v1/experiments/{experiment['id']}").json()["seed"] == 1
        assert client.get("/api/v1/experiments/none").status_code == 404
        assert client.post("/api/v1/experiments/none/run").status_code == 404
        bad = client.post(
            "/api/v1/experiments",
            json={"name": "e", "task_ids": ["ghost"], "configurations": [{"name": "m"}]},
        )
        assert bad.status_code == 404 and "ghost" in bad.json()["message"]
        run_id = client.post(f"/api/v1/experiments/{experiment['id']}/run").json()["run_ids"][0]
        for _ in range(100):
            view = client.get(f"/api/v1/runs/{run_id}").json()
            if view["status"] not in {"created", "queued", "provisioning", "running", "evaluating"}:
                break
            time.sleep(0.05)
        assert view["status"] in {"completed", "agent_failed"}
        assert client.get("/api/v1/runs?limit=1").json()[0]["id"] == run_id
        trace = client.get(f"/api/v1/runs/{run_id}/trace").json()
        assert trace["run_id"] == run_id and trace["timeline"]
        assert client.get(f"/api/v1/runs/{run_id}/metrics").status_code == 200
        results = client.get(f"/api/v1/experiments/{experiment['id']}/results").json()
        assert results["run_count"] == 1
        assert client.get("/api/v1/experiments/none/results").status_code == 404
        assert client.get("/api/v1/runs?limit=0").json()["code"] == "validation_error"
