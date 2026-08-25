"""Measure local trace and scheduler throughput; prints real observations as JSON."""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from agentscope.domain.models import RunId
from agentscope.scheduler.local import AsyncRunScheduler, ScheduledJob
from agentscope.tracing.models import EventType, TraceEvent
from agentscope.tracing.recorder import InMemoryTraceRecorder


async def measure(iterations: int, concurrency: int) -> dict[str, float | int]:
    trace = InMemoryTraceRecorder()
    run_id = RunId("run_performance")
    started = time.perf_counter()
    for _ in range(iterations):
        await trace.append(TraceEvent(run_id, 0, EventType.AGENT_STEP, "measurement"))
    trace_seconds = time.perf_counter() - started

    scheduler = AsyncRunScheduler(concurrency)
    started = time.perf_counter()
    futures = [await scheduler.submit(ScheduledJob(_noop)) for _ in range(iterations)]
    await asyncio.gather(*futures)
    scheduler_seconds = time.perf_counter() - started
    await scheduler.close()
    return {
        "iterations": iterations,
        "concurrency": concurrency,
        "trace_seconds": trace_seconds,
        "trace_events_per_second": iterations / trace_seconds,
        "scheduler_seconds": scheduler_seconds,
        "scheduler_jobs_per_second": iterations / scheduler_seconds,
    }


async def _noop() -> None:
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()
    if args.iterations < 1 or args.concurrency < 1:
        parser.error("values must be positive")
    print(json.dumps(asyncio.run(measure(args.iterations, args.concurrency)), indent=2))


if __name__ == "__main__":
    main()
