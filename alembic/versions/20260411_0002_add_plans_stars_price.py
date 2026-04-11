"""add plans.stars_price

Revision ID: 20260411_0002
Revises: 20260411_0001
Create Date: 2026-04-11 00:00:02

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260411_0002"
down_revision = "20260411_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("stars_price", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "stars_price")
