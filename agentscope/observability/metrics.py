from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import Counter, Gauge, Histogram, make_asgi_app


@dataclass(frozen=True, slots=True)
class Metrics:
    """AgentScope infrastructure metrics, separate from evaluated-agent metrics."""

    active_runs: Gauge
    queued_runs: Gauge
    run_duration: Histogram
    sandbox_startup: Histogram
    worker_failures: Counter
    api_errors: Counter

    @classmethod
    def create(cls) -> Metrics:
        return cls(
            Gauge("agentscope_active_runs", "Currently active evaluation runs"),
            Gauge("agentscope_queued_runs", "Currently queued evaluation runs"),
            Histogram("agentscope_run_duration_seconds", "End-to-end run duration"),
            Histogram("agentscope_sandbox_startup_seconds", "Sandbox provisioning duration"),
            Counter("agentscope_worker_failures_total", "Worker infrastructure failures"),
            Counter("agentscope_api_errors_total", "API errors", ("status",)),
        )


def prometheus_app() -> object:
    return make_asgi_app()
