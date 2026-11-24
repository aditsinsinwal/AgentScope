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
    task: asyncio.Task[Any] | None = None
    cancel_requested: bool = False
    # Awaited when the job is cancelled without a running task to unwind (e.g. still queued), so
    # its owner can record a terminal state. Must be idempotent.
    on_cancelled: Callable[[], Awaitable[None]] | None = None
    cancel_callback: asyncio.Task[None] | None = None


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
        """Request cancellation; returns False if the job is unknown or already finished."""
        job = self._jobs.get(job_id)
        if job is None or job.future is None or job.future.done():
            return False
        self._cancel_job(job)
        return job.future.cancel()

    def _cancel_job(self, job: ScheduledJob) -> None:
        job.cancel_requested = True
        if job.task is not None and not job.task.done():
            # Stop the running work too, so its sandbox context managers unwind.
            job.task.cancel()
        elif job.on_cancelled is not None and job.cancel_callback is None:
            # Never started (or between retries): nothing will unwind, so notify the owner.
            job.cancel_callback = asyncio.ensure_future(job.on_cancelled())

    async def cancel_and_wait(self, job_id: str, settle_seconds: float = 5.0) -> bool:
        """Cancel, then wait (bounded) until the job's task or cancel callback has settled."""
        job = self._jobs.get(job_id)
        cancelled = self.cancel(job_id)
        if job is not None:
            pending = {t for t in (job.task, job.cancel_callback) if t is not None and not t.done()}
            if pending:
                await asyncio.wait(pending, timeout=settle_seconds)
        return cancelled

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return
                if job.future is None or job.future.cancelled():
                    continue
                job.attempts += 1
                job.task = asyncio.ensure_future(job.execute())
                try:
                    result = await job.task
                except asyncio.CancelledError:
                    if not job.cancel_requested:
                        raise  # the worker itself is being cancelled
                    if not job.future.done():
                        job.future.cancel()
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
        """Cancel queued and running jobs, then stop workers; leaves no tasks behind."""
        for job in self._jobs.values():
            if job.future is not None and not job.future.done():
                self._cancel_job(job)
                job.future.cancel()
        for _ in self._workers:
            await self._queue.put(None)
        await asyncio.gather(*self._workers, return_exceptions=True)
        callbacks = [j.cancel_callback for j in self._jobs.values() if j.cancel_callback]
        if callbacks:
            await asyncio.gather(*callbacks, return_exceptions=True)
        self._workers.clear()
        self._jobs.clear()
