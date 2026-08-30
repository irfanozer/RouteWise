"""Create replayable RouteWise route runs.

Revision ID: 20260829_0001
Revises:
Create Date: 2026-08-29 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "route_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("network_snapshot", sa.JSON(), nullable=False),
        sa.Column("disruption_snapshot", sa.JSON(), nullable=True),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["route_runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_route_runs_created_at", "route_runs", ["created_at"])
    op.create_index("ix_route_runs_source_run_id", "route_runs", ["source_run_id"])


def downgrade() -> None:
    op.drop_index("ix_route_runs_source_run_id", table_name="route_runs")
    op.drop_index("ix_route_runs_created_at", table_name="route_runs")
    op.drop_table("route_runs")
