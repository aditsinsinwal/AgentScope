# Roadmap

## Implemented since the v0.1 plan

- [x] Prompt-suite evaluation: JSONL cases, deterministic checkers (`exact`, `regex`, `field_lines`, `json_keys`), artifacts, paired compare
- [x] Loopback-only Ollama and LM Studio providers, with a loopback guard on every base URL
- [x] Suite-report API (read-only, path-safe) and dashboard views: reports, detail, compare
- [x] Provider retry with backoff and jitter, typed `ProviderError`, agent loop caps
- [x] Scheduler cancellation unwinds running sandboxes; shutdown cancels queued and running jobs
- [x] API hardening: optional bearer token, body limit, request ids, uniform error envelope
- [x] CI: ruff, format check, strict mypy, coverage gate on Python 3.12 and 3.13; frontend typecheck, test and build

## v0.1 hardening

- Exercise Alembic downgrade/upgrade on a fresh PostgreSQL instance in CI.
- Durable database trace recorder and content-addressed artifact store.
- Dedicated worker daemon around leases, graceful shutdown, and reconciliation UI.
- Rootless Docker plus pinned seccomp/AppArmor policy and image signing/scanning.
- API authentication: a single optional bearer token is done. Open: RBAC, quotas, idempotency keys, and tenant isolation.
- Retry/backoff for transport errors, 429 and 5xx is done. Open: provider contract tests.

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
