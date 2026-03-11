"""merge heads

Revision ID: cffc4bf3e166
Revises: 4f6e3d2a1bcd, d8352a7d912c
Create Date: 2026-02-28 19:15:01.937785

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cffc4bf3e166'
down_revision: Union[str, None] = ('4f6e3d2a1bcd', 'd8352a7d912c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
