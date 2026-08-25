# Performance measurements

These are real development-machine observations, not product guarantees or model benchmarks.
They exist to validate the Phase 20 harness and should be regenerated for every release environment.

## 2026-08-23 local sample

Environment: Darwin 24.3.0, ARM64, Python 3.12.3, Docker Desktop 27.5.1. The tree was uncommitted
v0.1 development code. No other workload or warm-up control was applied.

`python scripts/performance.py --iterations 5000 --concurrency 4` observed:

| Microbenchmark | Observation |
|---|---:|
| In-memory trace appends | 209,271 events/s |
| No-op local scheduler jobs | 228,825 jobs/s |

Five sequential empty `DockerSandbox` provisions using an already-built/warm image observed
0.205, 0.120, 0.113, 0.119, and 0.123 seconds: median 0.120 seconds, maximum 0.205 seconds.

The trace and scheduler tests intentionally exclude PostgreSQL, model calls, repository work,
evaluation, and serialization. The Docker sample excludes image build/pull and contains only five
observations. They are useful smoke measurements, not capacity planning. A production report needs
repeated cold/warm trials, percentiles, confidence intervals, resource utilization, database-backed
traces, representative repository sizes, and documented competing load.
