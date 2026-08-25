from pathlib import Path

from fastapi.testclient import TestClient

from agentscope.api.app import create_app

ROOT = Path(__file__).parents[1]


def test_task_and_experiment_api() -> None:
    with TestClient(create_app(sandbox_kind="local")) as client:
        task_response = client.post(
            "/api/v1/tasks",
            json={"definition_path": str(ROOT / "examples/cart-empty-500/task.yaml")},
        )
        assert task_response.status_code == 201
        assert task_response.json()["id"] == "cart-empty-500"

        experiment_response = client.post(
            "/api/v1/experiments",
            json={
                "name": "mock baseline",
                "task_ids": ["cart-empty-500"],
                "configurations": [{"name": "mock"}],
                "seed": 42,
            },
        )
        assert experiment_response.status_code == 201
        experiment_id = experiment_response.json()["id"]
        run_response = client.post(f"/api/v1/experiments/{experiment_id}/run")
        assert run_response.status_code == 202
        assert len(run_response.json()["run_ids"]) == 1


def test_structured_not_found_error() -> None:
    with TestClient(create_app(sandbox_kind="local")) as client:
        response = client.get("/api/v1/runs/run_missing")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_health_reports_runtime_configuration() -> None:
    with TestClient(create_app(sandbox_kind="local", serve_frontend=False)) as client:
        response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0", "sandbox": "local"}


def test_production_dashboard_is_served() -> None:
    with TestClient(create_app(sandbox_kind="local")) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "AgentScope · Evaluation Dashboard" in response.text
