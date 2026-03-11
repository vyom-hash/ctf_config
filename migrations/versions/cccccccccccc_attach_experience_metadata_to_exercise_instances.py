"""Attach experience metadata to exercise instances.

Revision ID: cccccccccccc
Revises: f8135eeeb942
Create Date: 2026-03-02 13:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cccccccccccc"
down_revision: Union[str, None] = "f8135eeeb942"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "exercise_instances",
        sa.Column("experience_mode", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "exercise_instances",
        sa.Column("sub_category", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "exercise_instances",
        sa.Column(
            "isolation_strategy",
            sa.String(length=50),
            nullable=False,
            server_default="per_user",
        ),
    )


def downgrade() -> None:
    op.drop_column("exercise_instances", "isolation_strategy")
    op.drop_column("exercise_instances", "sub_category")
    op.drop_column("exercise_instances", "experience_mode")

