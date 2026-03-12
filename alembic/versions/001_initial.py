"""Initial migration

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tracklists",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "tracks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "tracklist_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tracklists.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("artist", sa.String(), nullable=True),
        sa.Column("timestamp_start", sa.Float(), nullable=False),
        sa.Column("timestamp_end", sa.Float(), nullable=True),
        sa.Column("snippet_path", sa.String(), nullable=True),
        sa.Column("raw_result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tracks")
    op.drop_table("tracklists")
