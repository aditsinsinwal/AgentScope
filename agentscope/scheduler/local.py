from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


class InfrastructureFailure(Exception):
    """Retryable failure before an agent outcome is established."""


@dataclass(slots=True)
class ScheduledJob:
    execute: Callable[[], Awaitable[Any]]
    id: str = field(default_factory=lambda: f"job_{uuid4().hex[:12]}")
    max_infrastructure_retries: int = 1
    attempts: int = 0
    future: asyncio.Future[Any] | None = None


class AsyncRunScheduler:
    """Bounded, cancellation-aware in-process worker pool."""

    def __init__(self, concurrency: int = 2) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        self.concurrency = concurrency
        self._queue: asyncio.Queue[ScheduledJob | None] = asyncio.Queue()
        self._workers: list[asyncio.Task[None]] = []
        self._jobs: dict[str, ScheduledJob] = {}

    async def start(self) -> None:
        if not self._workers:
            self._workers = [
                asyncio.create_task(self._worker(), name=f"agentscope-worker-{index}")
                for index in range(self.concurrency)
            ]

    async def submit(self, job: ScheduledJob) -> asyncio.Future[Any]:
        await self.start()
        job.future = asyncio.get_running_loop().create_future()
        self._jobs[job.id] = job
        await self._queue.put(job)
        return job.future

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.future is None or job.future.done():
            return False
        return job.future.cancel()

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return
                if job.future is None or job.future.cancelled():
                    continue
                job.attempts += 1
                try:
                    result = await job.execute()
                except InfrastructureFailure as exc:
                    if job.attempts <= job.max_infrastructure_retries:
                        await self._queue.put(job)
                    elif not job.future.done():
                        job.future.set_exception(exc)
                except Exception as exc:
                    # Agent/evaluation exceptions are outcomes, never silently retried.
                    if not job.future.done():
                        job.future.set_exception(exc)
                else:
                    if not job.future.done():
                        job.future.set_result(result)
            finally:
                self._queue.task_done()

    async def close(self) -> None:
        for _ in self._workers:
            await self._queue.put(None)
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
