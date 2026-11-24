from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentscope.api.app import create_app
from agentscope.api.middleware import safe_request_id, warn_if_unauthenticated

ROOT = Path(__file__).parents[1]
TOKEN = "s3cret-token-value"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def build(**kwargs: object) -> FastAPI:
    return create_app(sandbox_kind="local", serve_frontend=False, **kwargs)  # type: ignore[arg-type]


def test_no_token_means_open_local_dev() -> None:
    with TestClient(build()) as client:
        assert client.get("/api/v1/runs").status_code == 200


def test_token_required_for_api_but_not_health() -> None:
    with TestClient(build(api_token=TOKEN)) as client:
        assert client.get("/api/v1/health").status_code == 200
        for headers in (
            {},
            {"Authorization": "Bearer wrong"},
            {"Authorization": TOKEN},
            {"Authorization": f"Basic {TOKEN}"},
            {"Authorization": f"Bearer {TOKEN}x"},
        ):
            response = client.get("/api/v1/runs", headers=headers)
            assert response.status_code == 401, headers
            assert response.headers["www-authenticate"] == "Bearer"
            body = response.json()
            assert body["code"] == "unauthorized" and body["request_id"]
            assert TOKEN not in response.text
        assert client.get("/api/v1/runs", headers=AUTH).status_code == 200
        assert client.post("/api/v1/runs/x/cancel").status_code == 401


def test_token_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentscope.config import get_settings

    monkeypatch.setenv("AGENTSCOPE_API_TOKEN", TOKEN)
    get_settings.cache_clear()
    try:
        with TestClient(build()) as client:
            assert client.get("/api/v1/runs").status_code == 401
            assert client.get("/api/v1/runs", headers=AUTH).status_code == 200
    finally:
        get_settings.cache_clear()


def test_body_limit_by_content_length_and_chunked() -> None:
    with TestClient(build(max_request_bytes=200)) as client:
        big = {"definition_path": "x" * 500}
        response = client.post("/api/v1/tasks", json=big)
        assert response.status_code == 413
        assert response.json()["code"] == "payload_too_large"

        def chunks() -> Iterator[bytes]:
            for _ in range(10):
                yield b" " * 100

        chunked = client.post(
            "/api/v1/tasks", content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert chunked.status_code == 413
        assert chunked.headers["x-request-id"]
        small = client.post("/api/v1/tasks", json={"definition_path": "nope.yaml"})
        assert small.status_code != 413


def test_validation_error_envelope_hides_input_values() -> None:
    with TestClient(build()) as client:
        response = client.post("/api/v1/tasks", json={"definition_path": "", "extra": "hunter2"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error" and body["request_id"]
    assert {"loc", "message", "type"} <= set(body["details"][0])
    assert "hunter2" not in response.text


def test_404_and_405_use_envelope() -> None:
    with TestClient(build()) as client:
        missing = client.get("/api/v1/nope")
        wrong_method = client.delete("/api/v1/tasks")
        run_missing = client.get("/api/v1/runs/run_missing")
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    assert wrong_method.status_code == 405 and wrong_method.json()["code"] == "method_not_allowed"
    assert run_missing.json()["request_id"]


def test_unexpected_error_is_logged_not_leaked(caplog: pytest.LogCaptureFixture) -> None:
    app = build()

    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise RuntimeError("database password is hunter2")

    with TestClient(app, raise_server_exceptions=False) as client:
        with caplog.at_level(logging.ERROR, logger="agentscope.api"):
            response = client.get("/api/v1/boom", headers={"X-Request-ID": "req-123"})
    assert response.status_code == 500
    body = response.json()
    assert body == {
        "code": "internal_error",
        "message": "internal server error",
        "request_id": "req-123",
    }
    assert "hunter2" not in response.text and "Traceback" not in response.text
    assert response.headers["x-request-id"] == "req-123"
    assert any("req-123" in r.getMessage() for r in caplog.records)
    assert any("hunter2" in (r.exc_text or "") or r.exc_info for r in caplog.records)


def test_request_id_honoured_only_when_safe() -> None:
    assert safe_request_id("abc-123_X.y") == "abc-123_X.y"
    for bad in ("", None, "has space", "x" * 65, "a\nb", "<script>"):
        generated = safe_request_id(bad)
        assert generated != bad and len(generated) == 32
    with TestClient(build()) as client:
        ok = client.get("/api/v1/health", headers={"X-Request-ID": "trace-1"})
        bad = client.get("/api/v1/health", headers={"X-Request-ID": "bad id!"})
    assert ok.headers["x-request-id"] == "trace-1"
    assert bad.headers["x-request-id"] != "bad id!" and len(bad.headers["x-request-id"]) == 32


def test_cors_is_not_enabled() -> None:
    with TestClient(build()) as client:
        preflight = client.options(
            "/api/v1/runs",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
        )
        simple = client.get("/api/v1/runs", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in simple.headers


def test_startup_warning_only_for_exposed_unauthenticated_binding(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="agentscope.api"):
        assert not warn_if_unauthenticated("127.0.0.1", None)
        assert not warn_if_unauthenticated("0.0.0.0", TOKEN)
        assert warn_if_unauthenticated("0.0.0.0", None)
    assert len(caplog.records) == 1 and TOKEN not in caplog.text
