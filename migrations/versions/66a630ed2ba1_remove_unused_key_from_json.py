"""Remove unused key from json.

Revision ID: 66a630ed2ba1
Revises: b4c5d6e7f890
Create Date: 2026-03-06 23:41:23.979885

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '66a630ed2ba1'
down_revision: Union[str, None] = 'b4c5d6e7f890'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Keep resource tier tables; only normalize enable_jumphost default."""
    op.alter_column(
        "recipes",
        "enable_jumphost",
        existing_type=sa.BOOLEAN(),
        server_default=None,
        existing_nullable=False,
    )


def downgrade() -> None:
    """Restore original enable_jumphost default; leave resource tier tables intact."""
    op.alter_column(
        "recipes",
        "enable_jumphost",
        existing_type=sa.BOOLEAN(),
        server_default=sa.text("true"),
        existing_nullable=False,
    )
