"""Add recipe_version_id to exercise_instances.

Revision ID: aaaaaaaaaaaa
Revises: f8811264c4ee
Create Date: 2026-02-27 14:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "aaaaaaaaaaaa"
down_revision: Union[str, None] = "f8811264c4ee"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "exercise_instances",
        sa.Column(
            "recipe_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recipe_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ei_recipe_version_id",
        "exercise_instances",
        ["recipe_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ei_recipe_version_id", table_name="exercise_instances")
    op.drop_column("exercise_instances", "recipe_version_id")

