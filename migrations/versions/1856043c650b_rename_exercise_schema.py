"""Rename exercise schema.

Revision ID: 1856043c650b
Revises: 0fc752f7039c
Create Date: 2026-03-07 16:17:19.990511

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1856043c650b'
down_revision: Union[str, None] = '0fc752f7039c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the new PostgreSQL ENUM type before using it (idempotent)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'guidancetype') THEN
                CREATE TYPE guidancetype AS ENUM ('conceptual', 'directional', 'procedural');
            END IF;
        END $$
    """)
    # Alter column from hinttype to guidancetype (column "type" is reserved in SQL, so quote it)
    op.execute(
        'ALTER TABLE guidance_steps ALTER COLUMN type TYPE guidancetype USING "type"::text::guidancetype'
    )


def downgrade() -> None:
    # Revert column from guidancetype to hinttype (create hinttype if not exists)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hinttype') THEN
                CREATE TYPE hinttype AS ENUM ('conceptual', 'directional', 'procedural');
            END IF;
        END $$
    """)
    op.execute(
        'ALTER TABLE guidance_steps ALTER COLUMN type TYPE hinttype USING "type"::text::hinttype'
    )
    op.execute('DROP TYPE guidancetype')
