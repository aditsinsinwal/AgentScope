"""Allow unknown (NULL) token counts on trace events."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("trace_events", "input_tokens", existing_type=sa.Integer(), nullable=True)
    op.alter_column("trace_events", "output_tokens", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE trace_events SET input_tokens = 0 WHERE input_tokens IS NULL")
    op.execute("UPDATE trace_events SET output_tokens = 0 WHERE output_tokens IS NULL")
    op.alter_column("trace_events", "input_tokens", existing_type=sa.Integer(), nullable=False)
    op.alter_column("trace_events", "output_tokens", existing_type=sa.Integer(), nullable=False)
