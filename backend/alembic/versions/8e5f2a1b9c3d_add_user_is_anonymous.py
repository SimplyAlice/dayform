"""add user is_anonymous

Revision ID: 8e5f2a1b9c3d
Revises: 7c4d1a9e2b60
Create Date: 2026-10-08 20:30:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "8e5f2a1b9c3d"
down_revision: str | None = "7c4d1a9e2b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_anonymous",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_anonymous")
