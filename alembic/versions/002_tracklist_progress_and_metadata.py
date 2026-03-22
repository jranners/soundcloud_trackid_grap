"""Add tracklist progress and metadata columns

Revision ID: 002
Revises: 001
Create Date: 2026-03-21 11:40:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tracklists", sa.Column("task_id", sa.String(), nullable=True))
    op.add_column("tracklists", sa.Column("set_title", sa.String(), nullable=True))
    op.add_column("tracklists", sa.Column("cover_url", sa.String(), nullable=True))
    op.add_column(
        "tracklists",
        sa.Column("progress_percent", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column("tracklists", sa.Column("progress_message", sa.String(), nullable=True))
    op.add_column("tracklists", sa.Column("total_segments", sa.Float(), nullable=True))
    op.add_column("tracklists", sa.Column("processed_segments", sa.Float(), nullable=True))
    op.create_unique_constraint("uq_tracklists_task_id", "tracklists", ["task_id"])


def downgrade() -> None:
    op.drop_constraint("uq_tracklists_task_id", "tracklists", type_="unique")
    op.drop_column("tracklists", "processed_segments")
    op.drop_column("tracklists", "total_segments")
    op.drop_column("tracklists", "progress_message")
    op.drop_column("tracklists", "progress_percent")
    op.drop_column("tracklists", "cover_url")
    op.drop_column("tracklists", "set_title")
    op.drop_column("tracklists", "task_id")
