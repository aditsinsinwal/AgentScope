from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentscope.domain.errors import RunNotFoundError
from agentscope.domain.models import (
    AgentConfiguration,
    EvaluationResult,
    ExperimentRun,
    ModelConfiguration,
    RunId,
    RunMeasurements,
    Score,
    TaskId,
)
from agentscope.domain.states import FailureCategory, RunStatus
from agentscope.persistence.models import RunRecord, TraceRecord
from agentscope.tracing.models import EventType, TraceEvent


def _configuration_to_dict(configuration: AgentConfiguration) -> dict[str, Any]:
    model: dict[str, Any] | None = None
    if configuration.model:
        model = {
            "provider": configuration.model.provider,
            "model": configuration.model.model,
            "base_url": configuration.model.base_url,
            "temperature": configuration.model.temperature,
            "max_output_tokens": configuration.model.max_output_tokens,
        }
    return {
        "name": configuration.name,
        "model": model,
        "tools": list(configuration.tools),
        "system_prompt": configuration.system_prompt,
        "max_steps": configuration.max_steps,
    }


def _configuration_from_dict(value: dict[str, Any]) -> AgentConfiguration:
    raw_model = value.get("model")
    model = ModelConfiguration(**raw_model) if isinstance(raw_model, dict) else None
    return AgentConfiguration(
        name=str(value["name"]),
        model=model,
        tools=tuple(value.get("tools", ())),
        system_prompt=str(value.get("system_prompt", "")),
        max_steps=int(value.get("max_steps", 50)),
    )


def _result_to_dict(result: EvaluationResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "passed": result.passed,
        "public_passed": result.public_passed,
        "hidden_passed": result.hidden_passed,
        "constraints_satisfied": result.constraints_satisfied,
        "score": {
            "correctness": str(result.score.correctness),
            "regression_safety": str(result.score.regression_safety),
            "constraint_adherence": str(result.score.constraint_adherence),
            "efficiency": str(result.score.efficiency),
        },
        "duration_seconds": result.duration_seconds,
        "failure_category": result.failure_category.value if result.failure_category else None,
        "details": result.details,
    }


def _result_from_dict(value: dict[str, Any] | None) -> EvaluationResult | None:
    if value is None:
        return None
    score = value["score"]
    category = value.get("failure_category")
    return EvaluationResult(
        bool(value["passed"]),
        bool(value["public_passed"]),
        bool(value["hidden_passed"]),
        bool(value["constraints_satisfied"]),
        Score(
            Decimal(score["correctness"]),
            Decimal(score["regression_safety"]),
            Decimal(score["constraint_adherence"]),
            Decimal(score["efficiency"]),
        ),
        float(value["duration_seconds"]),
        FailureCategory(category) if category else None,
        str(value.get("details", "")),
    )


def _to_domain(record: RunRecord) -> ExperimentRun:
    return ExperimentRun(
        task_id=TaskId(record.task_id),
        agent_configuration=_configuration_from_dict(record.agent_configuration),
        id=RunId(record.id),
        status=RunStatus(record.status),
        seed=record.seed,
        task_hash=record.task_hash,
        environment_fingerprint=record.environment_fingerprint,
        created_at=record.created_at,
        updated_at=record.updated_at,
        result=_result_from_dict(record.result),
        measurements=RunMeasurements(**record.measurements),
        failure_message=record.failure_message,
    )


class SqlAlchemyRunRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def save(self, run: ExperimentRun) -> None:
        async with self.sessions() as session, session.begin():
            record = await session.get(RunRecord, str(run.id))
            values: dict[str, Any] = {
                "task_id": str(run.task_id),
                "status": run.status.value,
                "seed": run.seed,
                "agent_configuration": _configuration_to_dict(run.agent_configuration),
                "task_hash": run.task_hash,
                "environment_fingerprint": run.environment_fingerprint,
                "result": _result_to_dict(run.result),
                "measurements": {
                    "agent_duration_seconds": run.measurements.agent_duration_seconds,
                    "model_calls": run.measurements.model_calls,
                    "tool_calls": run.measurements.tool_calls,
                    "input_tokens": run.measurements.input_tokens,
                    "output_tokens": run.measurements.output_tokens,
                    "cached_tokens": run.measurements.cached_tokens,
                },
                "failure_message": run.failure_message,
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            }
            if record is None:
                session.add(RunRecord(id=str(run.id), **values))
            else:
                for name, value in values.items():
                    setattr(record, name, value)

    async def get(self, run_id: RunId) -> ExperimentRun:
        async with self.sessions() as session:
            record = await session.get(RunRecord, str(run_id))
            if record is None:
                raise RunNotFoundError(str(run_id))
            return _to_domain(record)

    async def list(self, offset: int = 0, limit: int = 100) -> Sequence[ExperimentRun]:
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(RunRecord)
                    .order_by(RunRecord.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            ).all()
            return tuple(_to_domain(record) for record in records)


class SqlAlchemyTraceRecorder:
    """Durable, per-run sequenced PostgreSQL trace recorder."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def append(self, event: TraceEvent) -> TraceEvent:
        async with self.sessions() as session, session.begin():
            # Lock the parent run so concurrent appenders serialize sequence allocation.
            run_exists = await session.scalar(
                select(RunRecord.id).where(RunRecord.id == str(event.run_id)).with_for_update()
            )
            if run_exists is None:
                raise RunNotFoundError(str(event.run_id))
            current = await session.scalar(
                select(func.max(TraceRecord.sequence)).where(
                    TraceRecord.run_id == str(event.run_id)
                )
            )
            recorded = replace(event, sequence=(current or 0) + 1)
            session.add(
                TraceRecord(
                    run_id=str(recorded.run_id),
                    sequence=recorded.sequence,
                    event_type=recorded.event_type.value,
                    name=recorded.name,
                    timestamp=recorded.timestamp,
                    duration_ms=recorded.duration_ms,
                    status=recorded.status,
                    input_summary=recorded.input_summary,
                    output_summary=recorded.output_summary,
                    error=recorded.error,
                    model=recorded.model,
                    input_tokens=recorded.input_tokens,
                    output_tokens=recorded.output_tokens,
                    event_metadata=recorded.metadata,
                )
            )
            return recorded

    async def events(self, run_id: RunId) -> Sequence[TraceEvent]:
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(TraceRecord)
                    .where(TraceRecord.run_id == str(run_id))
                    .order_by(TraceRecord.sequence)
                )
            ).all()
            return tuple(
                TraceEvent(
                    run_id,
                    record.sequence,
                    EventType(record.event_type),
                    record.name,
                    record.timestamp,
                    record.duration_ms,
                    record.status,
                    record.input_summary,
                    record.output_summary,
                    record.error,
                    record.model,
                    record.input_tokens,
                    record.output_tokens,
                    record.event_metadata,
                )
                for record in records
            )
