from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TaskRecord(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExperimentRecord(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    seed: Mapped[int] = mapped_column(Integer)
    task_ids: Mapped[list[str]] = mapped_column(JSONB)
    configurations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunRecord(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("tasks.id"), index=True)
    experiment_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("experiments.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    seed: Mapped[int] = mapped_column(Integer)
    agent_configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    task_hash: Mapped[str] = mapped_column(String(64), default="")
    environment_fingerprint: Mapped[str] = mapped_column(String(200), default="")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    measurements: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    failure_message: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(100), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    traces: Mapped[list[TraceRecord]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_runs_claim", "status", "lease_until", "created_at"),)


class TraceRecord(Base):
    __tablename__ = "trace_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_ms: Mapped[float | None]
    status: Mapped[str] = mapped_column(String(32))
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    run: Mapped[RunRecord] = relationship(back_populates="traces")

    __table_args__ = (Index("uq_trace_run_sequence", "run_id", "sequence", unique=True),)


class MetricRecord(Base):
    __tablename__ = "metrics"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit: Mapped[str] = mapped_column(String(32))
    metric_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class WorkerRecord(Base):
    __tablename__ = "workers"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
