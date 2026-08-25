from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Protocol

from agentscope.domain.models import RunId
from agentscope.tracing.models import EventType, TraceEvent


class TraceRecorder(Protocol):
    async def append(self, event: TraceEvent) -> TraceEvent: ...

    async def events(self, run_id: RunId) -> Sequence[TraceEvent]: ...


class InMemoryTraceRecorder:
    """Concurrency-safe recorder used by local runs and tests."""

    def __init__(self) -> None:
        self._events: dict[RunId, list[TraceEvent]] = {}
        self._lock = asyncio.Lock()

    async def append(self, event: TraceEvent) -> TraceEvent:
        async with self._lock:
            values = self._events.setdefault(event.run_id, [])
            recorded = replace(event, sequence=len(values) + 1)
            values.append(recorded)
            return recorded

    async def events(self, run_id: RunId) -> Sequence[TraceEvent]:
        async with self._lock:
            return tuple(self._events.get(run_id, ()))


class JsonlTraceRecorder:
    """Bounded JSONL artifact recorder suitable for local CLI replay."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._locks: dict[RunId, asyncio.Lock] = {}

    def _path(self, run_id: RunId) -> Path:
        if not str(run_id).startswith("run_") or not str(run_id).replace("_", "").isalnum():
            raise ValueError("invalid run id")
        return self.root / f"{run_id}.jsonl"

    async def append(self, event: TraceEvent) -> TraceEvent:
        lock = self._locks.setdefault(event.run_id, asyncio.Lock())
        async with lock:
            existing = await self.events(event.run_id)
            recorded = replace(event, sequence=len(existing) + 1)
            path = self._path(event.run_id)
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            payload = {
                "run_id": str(recorded.run_id),
                "sequence": recorded.sequence,
                "event_type": recorded.event_type.value,
                "name": recorded.name,
                "timestamp": recorded.timestamp.isoformat(),
                "duration_ms": recorded.duration_ms,
                "status": recorded.status,
                "input_summary": recorded.input_summary,
                "output_summary": recorded.output_summary,
                "error": recorded.error,
                "model": recorded.model,
                "input_tokens": recorded.input_tokens,
                "output_tokens": recorded.output_tokens,
                "metadata": recorded.metadata,
            }

            def write_line() -> None:
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")

            await asyncio.to_thread(write_line)
            return recorded

    async def events(self, run_id: RunId) -> Sequence[TraceEvent]:
        path = self._path(run_id)
        if not path.exists():
            return ()

        def read() -> tuple[TraceEvent, ...]:
            values: list[TraceEvent] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                item = json.loads(line)
                values.append(
                    TraceEvent(
                        RunId(item["run_id"]),
                        int(item["sequence"]),
                        EventType(item["event_type"]),
                        str(item["name"]),
                        datetime.fromisoformat(item["timestamp"]),
                        item.get("duration_ms"),
                        str(item.get("status", "success")),
                        item.get("input_summary"),
                        item.get("output_summary"),
                        item.get("error"),
                        item.get("model"),
                        int(item.get("input_tokens", 0)),
                        int(item.get("output_tokens", 0)),
                        item.get("metadata", {}),
                    )
                )
            return tuple(values)

        return await asyncio.to_thread(read)
