"""Added Exercise Instance feature.

Revision ID: f8811264c4ee
Revises: 4f6e3d2a1bcd
Create Date: 2026-02-27 13:33:20.593854

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f8811264c4ee'
down_revision: Union[str, None] = '4f6e3d2a1bcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op migration.

    The Exercise Instance tables and indexes were already created in
    4f6e3d2a1bcd_add_exercise_instance_tables. This autogen migration would
    otherwise drop and recreate those tables, which is undesirable and
    fails due to foreign key dependencies. We keep this revision as a
    logical marker without changing the schema.
    """
    pass


def downgrade() -> None:
    """No-op downgrade for the no-op upgrade in this revision."""
    pass
