from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from agentscope.api import suites as suites_module
from agentscope.api.app import create_app
from agentscope.cli import app as cli_app

EXAMPLE = Path(__file__).parents[1] / "examples/suites/task-cards"
TOKEN = "s3cret-token-value"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def make_report(root: Path, name: str, replay: str) -> Path:
    out = root / name
    result = CliRunner().invoke(
        cli_app,
        [
            "suite", "run", "--suite", str(EXAMPLE / "suite.yaml"),
            "--provider", "replay",
            "--replay-outputs", str(EXAMPLE / f"replay-{replay}.outputs.jsonl"),
            "--out", str(out),
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    return out


@pytest.fixture
def reports(tmp_path: Path) -> Path:
    root = tmp_path / "reports"
    root.mkdir()
    make_report(root, "good", "good")
    make_report(root, "chatty", "chatty")
    return root


def client_for(root: Path, **kwargs: object) -> TestClient:
    application = create_app(
        sandbox_kind="local",
        serve_frontend=False,
        reports_dir=root,
        **kwargs,  # type: ignore[arg-type]
    )
    return TestClient(application)


def test_list_and_get(reports: Path) -> None:
    with client_for(reports) as client:
        rows = client.get("/api/v1/suite-reports").json()
        assert {r["report_id"] for r in rows} == {"good", "chatty"}
        good = next(r for r in rows if r["report_id"] == "good")
        assert (
            good["source"] == "replay" and good["n"] == 8 and good["suite_id"] == "task-cards-demo"
        )
        full = client.get("/api/v1/suite-reports/good")
        assert full.status_code == 200
        assert full.json()["aggregate"]["n"] == 8 and len(full.json()["cases"]) == 8


def test_missing_dir_lists_empty(tmp_path: Path) -> None:
    with client_for(tmp_path / "nope") as client:
        assert client.get("/api/v1/suite-reports").json() == []
        response = client.get("/api/v1/suite-reports/x")
        assert response.status_code == 404 and response.json()["code"] == "not_found"
        assert response.json()["request_id"]


def test_invalid_report_skipped_in_list_and_422_on_get(
    reports: Path, caplog: pytest.LogCaptureFixture
) -> None:
    broken = reports / "broken"
    broken.mkdir()
    (broken / "results.json").write_text(json.dumps({"schema_version": 1}))
    garbage = reports / "garbage"
    garbage.mkdir()
    (garbage / "results.json").write_text("{not json")
    (reports / "stray.txt").write_text("x")
    with client_for(reports) as client, caplog.at_level(logging.WARNING):
        rows = client.get("/api/v1/suite-reports").json()
        assert {r["report_id"] for r in rows} == {"good", "chatty"}
        assert "skipping report 'broken'" in caplog.text
        for name in ("broken", "garbage"):
            response = client.get(f"/api/v1/suite-reports/{name}")
            assert response.status_code == 422
            assert response.json()["code"] == "invalid_report"


def test_wrong_schema_version(reports: Path) -> None:
    path = reports / "good" / "results.json"
    data = json.loads(path.read_text())
    data["schema_version"] = 99
    path.write_text(json.dumps(data))
    with client_for(reports) as client:
        assert client.get("/api/v1/suite-reports/good").status_code == 422


def test_size_cap(reports: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(suites_module, "MAX_RESULTS_BYTES", 100)
    with client_for(reports) as client:
        response = client.get("/api/v1/suite-reports/good")
        assert response.status_code == 422 and response.json()["code"] == "report_too_large"
        assert client.get("/api/v1/suite-reports").json() == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/suite-reports/..",
        "/api/v1/suite-reports/%2e%2e",
        "/api/v1/suite-reports/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "/api/v1/suite-reports/..%2f..%2fetc",
        "/api/v1/suite-reports/%2fetc%2fpasswd",
        "/api/v1/suite-reports/.hidden",
        "/api/v1/suite-reports/good%00",
    ],
)
def test_traversal_rejected(reports: Path, path: str) -> None:
    secret = reports.parent / "secret"
    secret.mkdir()
    (secret / "results.json").write_text((reports / "good" / "results.json").read_text())
    with client_for(reports) as client:
        response = client.get(path)
        assert response.status_code in (400, 404)
        assert "task-cards-demo" not in response.text


def test_symlink_escape_rejected(reports: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "results.json").write_text((reports / "good" / "results.json").read_text())
    (reports / "linkdir").symlink_to(outside, target_is_directory=True)
    real = reports / "filelink"
    real.mkdir()
    (real / "results.json").symlink_to(outside / "results.json")
    with client_for(reports) as client:
        assert client.get("/api/v1/suite-reports/linkdir").status_code == 404
        assert client.get("/api/v1/suite-reports/filelink").status_code == 404
        ids = {r["report_id"] for r in client.get("/api/v1/suite-reports").json()}
        assert ids == {"good", "chatty"}


def test_compare(reports: Path) -> None:
    with client_for(reports) as client:
        response = client.get("/api/v1/suite-compare", params={"a": "chatty", "b": "good"})
        assert response.status_code == 200
        body = response.json()
        assert body["n_paired"] == 8
        assert body["b_better"] + body["tie"] + body["a_better"] == 8
        assert body["passed_b_only"] > 0 and body["a_source"] == "replay"
        assert body["a"]["report_id"] == "chatty" and isinstance(body["warnings"], list)
        missing = client.get("/api/v1/suite-compare", params={"a": "chatty", "b": "zzz"})
        assert missing.status_code == 404
        bad = client.get("/api/v1/suite-compare", params={"a": "..", "b": "good"})
        assert bad.status_code == 400
        assert client.get("/api/v1/suite-compare").status_code == 422


def test_compare_fingerprint_mismatch(reports: Path) -> None:
    path = reports / "chatty" / "results.json"
    data = json.loads(path.read_text())
    data["suite"]["fingerprint"] = "0" * 64
    path.write_text(json.dumps(data))
    with client_for(reports) as client:
        params = {"a": "chatty", "b": "good"}
        assert client.get("/api/v1/suite-compare", params=params).status_code == 422
        ok = client.get("/api/v1/suite-compare", params={**params, "allow_mismatch": True})
        assert ok.status_code == 200 and ok.json()["fingerprint_match"] is False


def test_auth_required_when_token_set(reports: Path) -> None:
    with client_for(reports, api_token=TOKEN) as client:
        for path in (
            "/api/v1/suite-reports",
            "/api/v1/suite-reports/good",
            "/api/v1/suite-compare?a=good&b=chatty",
        ):
            assert client.get(path).status_code == 401
            assert client.get(path, headers=AUTH).status_code == 200


def test_report_named_compare_is_not_listed(reports: Path) -> None:
    make_report(reports, "compare", "good")
    with client_for(reports) as client:
        ids = {r["report_id"] for r in client.get("/api/v1/suite-reports").json()}
        assert "compare" not in ids and ids == {"good", "chatty"}
        # Compare lives at its own path, so the id is still addressable directly.
        assert client.get("/api/v1/suite-reports/compare").status_code == 200
