"""Deployment: recipe_spec holds jumphost_unit and access_gateway; add exercises JSONB.

Revision ID: e2f3a4b5c6d7
Revises: fb8af0b30bfc
Create Date: 2026-02-26 14:00:00.000000

- Drop access_gateway column (moved into recipe_spec).
- Drop jumphost_unit column if present (jumphost_unit lives in recipe_spec snapshot).
- Add exercises JSONB column for exercise info snapshot.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "fb8af0b30bfc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("deployments", "access_gateway")
    op.execute("ALTER TABLE deployments DROP COLUMN IF EXISTS jumphost_unit")
    op.add_column(
        "deployments",
        sa.Column("exercises", JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("deployments", "exercises")
    op.add_column(
        "deployments",
        sa.Column("access_gateway", JSONB(astext_type=sa.Text()), nullable=True),
    )
    # jumphost_unit was optional; no need to re-add if it was dropped
