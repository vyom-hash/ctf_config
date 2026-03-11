"""add enable_jumphost flag to recipes

Revision ID: fe12c3ab45d6
Revises: f1ffeac1eb61
Create Date: 2026-03-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fe12c3ab45d6"
down_revision: Union[str, None] = "f1ffeac1eb61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recipes",
        sa.Column(
            "enable_jumphost",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("recipes", "enable_jumphost")

