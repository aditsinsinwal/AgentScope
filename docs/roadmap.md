# Roadmap

## v0.1 hardening

- Exercise Alembic downgrade/upgrade on a fresh PostgreSQL instance in CI.
- Durable database trace recorder and content-addressed artifact store.
- Dedicated worker daemon around leases, graceful shutdown, and reconciliation UI.
- Rootless Docker plus pinned seccomp/AppArmor policy and image signing/scanning.
- API authentication, RBAC, quotas, idempotency keys, and tenant isolation.
- Provider contract tests and retry/backoff policy for pre-response transport failures.

## v0.2 evidence

- Run the five-task suite across repeated paired configurations.
- Confidence intervals and paired outcome exports without automatic significance language.
- Benchmark AgentScope startup, throughput, trace writes, database latency, and memory on documented
  hardware using `scripts/performance.py` and Docker/PostgreSQL integration harnesses.
- Prometheus dashboards and configured OpenTelemetry exporter.

## Later

Object storage, multi-language images, resumable artifact upload, Redis only if measurements justify
it, multiple provider adapters, trace snapshots/forking, and a production React reporting UI. Semantic
LLM annotations may supplement—but never override—objective evaluation.
