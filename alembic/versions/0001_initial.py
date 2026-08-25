"""Initial AgentScope schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_tasks_fingerprint", "tasks", ["fingerprint"])
    op.create_table(
        "experiments",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("task_ids", postgresql.JSONB(), nullable=False),
        sa.Column("configurations", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "workers",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_workers_heartbeat_at", "workers", ["heartbeat_at"])
    op.create_table(
        "runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("experiment_id", sa.String(32), sa.ForeignKey("experiments.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("agent_configuration", postgresql.JSONB(), nullable=False),
        sa.Column("task_hash", sa.String(64), nullable=False),
        sa.Column("environment_fingerprint", sa.String(200), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("measurements", postgresql.JSONB(), nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.String(100), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_runs_task_id", "runs", ["task_id"])
    op.create_index("ix_runs_experiment_id", "runs", ["experiment_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_worker_id", "runs", ["worker_id"])
    op.create_index("ix_runs_lease_until", "runs", ["lease_until"])
    op.create_index("ix_runs_claim", "runs", ["status", "lease_until", "created_at"])
    op.create_table(
        "trace_events",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "run_id", sa.String(32), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("event_metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_trace_events_run_id", "trace_events", ["run_id"])
    op.create_index("ix_trace_events_event_type", "trace_events", ["event_type"])
    op.create_index("ix_trace_events_timestamp", "trace_events", ["timestamp"])
    op.create_index("uq_trace_run_sequence", "trace_events", ["run_id", "sequence"], unique=True)
    op.create_table(
        "metrics",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column(
            "run_id", sa.String(32), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("metric_metadata", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_metrics_run_id", "metrics", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_metrics_run_id", table_name="metrics")
    op.drop_table("metrics")
    op.drop_index("uq_trace_run_sequence", table_name="trace_events")
    op.drop_index("ix_trace_events_timestamp", table_name="trace_events")
    op.drop_index("ix_trace_events_event_type", table_name="trace_events")
    op.drop_index("ix_trace_events_run_id", table_name="trace_events")
    op.drop_table("trace_events")
    for name in (
        "ix_runs_claim",
        "ix_runs_lease_until",
        "ix_runs_worker_id",
        "ix_runs_status",
        "ix_runs_experiment_id",
        "ix_runs_task_id",
    ):
        op.drop_index(name, table_name="runs")
    op.drop_table("runs")
    op.drop_index("ix_workers_heartbeat_at", table_name="workers")
    op.drop_table("workers")
    op.drop_table("experiments")
    op.drop_index("ix_tasks_fingerprint", table_name="tasks")
    op.drop_table("tasks")
