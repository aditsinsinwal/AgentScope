"""Run a prompt suite against a chat model with bounded concurrency and tracing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Literal
from uuid import uuid4

from agentscope.domain.models import RunId, utc_now
from agentscope.suites.checkers import CaseCheck, Checker, build_checker
from agentscope.suites.models import PromptSuite, SuiteCase
from agentscope.suites.providers import (
    CaseAwareChatModel,
    ChatCompletion,
    ChatMessage,
    ChatModel,
    ReplayChatModel,
    redact,
)
from agentscope.tracing.models import EventType, TraceEvent


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    case_id: str
    output: str | None
    completion: ChatCompletion | None
    check: CaseCheck | None
    error: str | None
    wall_ms: float

    @property
    def ok(self) -> bool:
        return self.error is None and self.output is not None


@dataclass(frozen=True, slots=True)
class SuiteRunResult:
    run_id: RunId
    suite: PromptSuite
    outcomes: tuple[CaseOutcome, ...]  # always in suite case order
    source: Literal["generated", "replay"]
    provider: str
    model: str
    base_url_host: str | None
    concurrency: int
    case_timeout_seconds: float
    trace_text: bool
    started_at: datetime
    finished_at: datetime
    replay_unused_ids: tuple[str, ...] | None = None

    @property
    def n_failed(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.ok)


class SuiteTraceWriter:
    """Append-only JSONL trace using the TraceEvent schema of the existing recorder."""

    def __init__(self, path: Path, run_id: RunId) -> None:
        self.run_id = run_id
        self._path = path
        self._sequence = 0
        self._lock = asyncio.Lock()
        self._stream: IO[str] | None = None

    async def append(self, event: TraceEvent) -> None:
        async with self._lock:
            if self._stream is None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._stream = self._path.open("a", encoding="utf-8")
            self._sequence += 1
            payload: dict[str, Any] = {
                "run_id": str(event.run_id),
                "sequence": self._sequence,
                "event_type": event.event_type.value,
                "name": event.name,
                "timestamp": event.timestamp.isoformat(),
                "duration_ms": event.duration_ms,
                "status": event.status,
                "input_summary": event.input_summary,
                "output_summary": event.output_summary,
                "error": event.error,
                "model": event.model,
                "input_tokens": event.input_tokens,
                "output_tokens": event.output_tokens,
                "metadata": event.metadata,
            }
            self._stream.write(
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
            )
            self._stream.flush()

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class SuiteRunner:
    def __init__(
        self,
        suite: PromptSuite,
        model: ChatModel | CaseAwareChatModel,
        *,
        provider: str,
        model_name: str,
        base_url_host: str | None = None,
        concurrency: int = 1,
        case_timeout_seconds: float = 120.0,
        trace: SuiteTraceWriter | None = None,
        trace_text: bool = True,
        secrets: tuple[str, ...] = (),
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if case_timeout_seconds <= 0:
            raise ValueError("case_timeout_seconds must be positive")
        self.suite = suite
        self.model = model
        self.provider = provider
        self.model_name = model_name
        self.base_url_host = base_url_host
        self.concurrency = concurrency
        self.case_timeout_seconds = case_timeout_seconds
        self.trace = trace
        self.trace_text = trace_text
        self.secrets = secrets
        self._checker: Checker = build_checker(suite.checker)

    def _messages(self, case: SuiteCase) -> list[ChatMessage]:
        messages: list[ChatMessage] = []
        if self.suite.system_prompt is not None:
            messages.append(ChatMessage("system", self.suite.system_prompt))
        messages.append(ChatMessage("user", case.prompt))
        return messages

    def _text(self, text: str) -> str:
        # Prompts/outputs stay on this machine. With trace_text=False only the length
        # and a hash are stored.
        if self.trace_text:
            return redact(text, self.secrets)
        return f"chars={len(text)} sha256={_digest(text)}"

    async def _emit(self, event: TraceEvent) -> None:
        if self.trace is not None:
            await self.trace.append(event)

    async def run(self) -> SuiteRunResult:
        run_id = self.trace.run_id if self.trace else RunId(f"run_{uuid4().hex}")
        started = utc_now()
        await self._emit(
            TraceEvent(
                run_id,
                0,
                EventType.RUN_STATE,
                "suite_started",
                metadata={
                    "suite_id": self.suite.id,
                    "suite_fingerprint": self.suite.fingerprint,
                    "provider": self.provider,
                    "model": self.model_name,
                    "n_cases": len(self.suite.cases),
                    "concurrency": self.concurrency,
                    "trace_text": self.trace_text,
                },
            )
        )
        semaphore = asyncio.Semaphore(self.concurrency)
        tasks: list[asyncio.Task[CaseOutcome]] = []

        async def guarded(case: SuiteCase) -> CaseOutcome:
            async with semaphore:
                return await self._run_case(run_id, case)

        # TaskGroup: if the caller cancels, every in-flight case is cancelled and awaited.
        async with asyncio.TaskGroup() as group:
            for case in self.suite.cases:
                tasks.append(group.create_task(guarded(case)))
        outcomes = tuple(task.result() for task in tasks)
        finished = utc_now()
        result = SuiteRunResult(
            run_id=run_id,
            suite=self.suite,
            outcomes=outcomes,
            source="replay" if isinstance(self.model, ReplayChatModel) else "generated",
            provider=self.provider,
            model=self.model_name,
            base_url_host=self.base_url_host,
            concurrency=self.concurrency,
            case_timeout_seconds=self.case_timeout_seconds,
            trace_text=self.trace_text,
            started_at=started.astimezone(UTC),
            finished_at=finished.astimezone(UTC),
            replay_unused_ids=(
                tuple(self.model.unused_ids) if isinstance(self.model, ReplayChatModel) else None
            ),
        )
        await self._emit(
            TraceEvent(
                run_id,
                0,
                EventType.RUN_STATE,
                "suite_finished",
                status="success" if result.n_failed == 0 else "error",
                metadata={"n_cases": len(outcomes), "n_failed": result.n_failed},
            )
        )
        return result

    async def _call(self, case: SuiteCase) -> ChatCompletion:
        messages = self._messages(case)
        params = self.suite.generation
        async with asyncio.timeout(self.case_timeout_seconds):
            if isinstance(self.model, CaseAwareChatModel):
                return await self.model.complete_for_case(case.id, messages, params)
            return await self.model.complete(messages, params)

    async def _run_case(self, run_id: RunId, case: SuiteCase) -> CaseOutcome:
        started = time.monotonic()
        try:
            completion = await self._call(case)
            completion.text.encode("utf-8")  # lone surrogates cannot be written; fail the case
            # Off the event loop: other cases keep progressing while a check runs.
            check = await asyncio.to_thread(self._checker.check, completion.text, case.reference)
        except Exception as exc:  # per-case isolation; CancelledError is not an Exception
            wall_ms = (time.monotonic() - started) * 1000
            message = redact(f"{type(exc).__name__}: {exc}", self.secrets)
            if isinstance(exc, TimeoutError):
                message = f"TimeoutError: case exceeded {self.case_timeout_seconds}s"
            await self._emit(
                TraceEvent(
                    run_id,
                    0,
                    EventType.MODEL_CALL,
                    f"case:{case.id}",
                    duration_ms=wall_ms,
                    status="error",
                    input_summary=self._text(case.prompt),
                    error=message,
                    model=self.model_name,
                    metadata={"case_id": case.id},
                )
            )
            return CaseOutcome(case.id, None, None, None, message, wall_ms)
        wall_ms = (time.monotonic() - started) * 1000
        await self._emit(
            TraceEvent(
                run_id,
                0,
                EventType.MODEL_CALL,
                f"case:{case.id}",
                duration_ms=completion.latency_ms,
                input_summary=self._text(case.prompt),
                output_summary=self._text(completion.text),
                model=completion.model,
                input_tokens=completion.prompt_tokens or 0,
                output_tokens=completion.completion_tokens or 0,
                metadata={
                    "case_id": case.id,
                    "finish_reason": completion.finish_reason,
                    "tokens_known": completion.prompt_tokens is not None
                    and completion.completion_tokens is not None,
                },
            )
        )
        await self._emit(
            TraceEvent(
                run_id,
                0,
                EventType.EVALUATION,
                f"check:{case.id}",
                status="success" if check.passed else "failed",
                output_summary=check.detail,
                metadata={
                    "case_id": case.id,
                    "passed": check.passed,
                    "score": check.score,
                    "format_valid": check.format_valid,
                },
            )
        )
        return CaseOutcome(case.id, completion.text, completion, check, None, wall_ms)
