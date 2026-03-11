"""merge_all_heads

Revision ID: cb7acd4e5032
Revises: 11e974b4f919, 2739230d7948, 418cb2437e80
Create Date: 2026-03-05 08:42:10.146567

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb7acd4e5032'
down_revision: Union[str, None] = ('11e974b4f919', '2739230d7948', '418cb2437e80')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
