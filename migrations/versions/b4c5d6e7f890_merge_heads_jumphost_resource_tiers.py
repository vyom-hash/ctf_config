"""merge heads: enable_jumphost and restore_resource_tier_tables

Revision ID: b4c5d6e7f890
Revises: a2b3c4d5e6f7, fe12c3ab45d6
Create Date: 2026-03-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f890"
down_revision: Union[str, None] = ("a2b3c4d5e6f7", "fe12c3ab45d6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
