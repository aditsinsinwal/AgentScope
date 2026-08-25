from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Protocol

from agentscope.domain.errors import RunNotFoundError
from agentscope.domain.models import ExperimentRun, RunId


class RunRepository(Protocol):
    async def save(self, run: ExperimentRun) -> None: ...

    async def get(self, run_id: RunId) -> ExperimentRun: ...

    async def list(self, offset: int = 0, limit: int = 100) -> Sequence[ExperimentRun]: ...


class InMemoryRunRepository:
    def __init__(self) -> None:
        self._runs: dict[RunId, ExperimentRun] = {}
        self._lock = asyncio.Lock()

    async def save(self, run: ExperimentRun) -> None:
        async with self._lock:
            self._runs[run.id] = run

    async def get(self, run_id: RunId) -> ExperimentRun:
        async with self._lock:
            try:
                return self._runs[run_id]
            except KeyError as exc:
                raise RunNotFoundError(str(run_id)) from exc

    async def list(self, offset: int = 0, limit: int = 100) -> Sequence[ExperimentRun]:
        async with self._lock:
            newest_first = tuple(reversed(self._runs.values()))
            return newest_first[offset : offset + limit]
