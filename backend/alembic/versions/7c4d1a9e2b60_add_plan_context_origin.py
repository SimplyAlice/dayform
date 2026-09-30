"""add plan context origin

Revision ID: 7c4d1a9e2b60
Revises: 4d8f1e2a3c5b
Create Date: 2026-09-27 13:10:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "7c4d1a9e2b60"
down_revision: str | None = "4d8f1e2a3c5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "planning_contexts",
        sa.Column("origin", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("planning_contexts", "origin")
