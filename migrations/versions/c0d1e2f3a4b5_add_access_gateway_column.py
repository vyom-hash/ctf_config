"""Add access_gateway column to deployments (no longer stored in recipe_spec).

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-02-26 19:00:00.000000

- Add access_gateway JSONB column; recipe_spec no longer contains access_gateway key.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "deployments",
        sa.Column("access_gateway", JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deployments", "access_gateway")
