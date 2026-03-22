"""Add per-track confidence metrics columns

Revision ID: 003
Revises: 002
Create Date: 2026-03-22 13:55:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tracks",
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "tracks",
        sa.Column("num_snippets", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "tracks",
        sa.Column("num_consistent_snippets", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("tracks", sa.Column("raw_matches_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("tracks", "raw_matches_json")
    op.drop_column("tracks", "num_consistent_snippets")
    op.drop_column("tracks", "num_snippets")
    op.drop_column("tracks", "confidence_score")
