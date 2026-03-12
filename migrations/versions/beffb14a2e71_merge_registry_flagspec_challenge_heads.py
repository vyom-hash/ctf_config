"""merge_registry_flagspec_challenge_heads

Revision ID: beffb14a2e71
Revises: 29486b684d81, b2a99ec064d9, b52865e0e19b
Create Date: 2026-03-11 18:36:06.804294

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'beffb14a2e71'
down_revision: Union[str, None] = ('29486b684d81', 'b2a99ec064d9', 'b52865e0e19b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
