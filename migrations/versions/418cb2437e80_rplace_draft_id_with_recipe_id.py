"""Replace draft_id with recipe_id in recipe_versions and recipe_approvals.

Both tables previously referenced recipe_drafts(id) via draft_id.
We now reference recipes(id) via recipe_id — eliminating the dependency
on the recipe_drafts pivot table for versioning and approval records.

Revision ID: 418cb2437e80
Revises: c4e73570d74a
Create Date: 2026-03-02 14:08:38.875146

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '418cb2437e80'
down_revision: Union[str, None] = 'c4e73570d74a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── recipe_versions ───────────────────────────────────────────────────────
    # 1. Drop old FK (→ recipe_drafts.id)
    op.drop_constraint('recipe_versions_draft_id_fkey', 'recipe_versions', type_='foreignkey')
    # 2. Drop unique constraint that included draft_id
    op.drop_constraint('uq_draft_version', 'recipe_versions', type_='unique')
    # 3. Rename column
    op.alter_column('recipe_versions', 'draft_id', new_column_name='recipe_id')
    # 4. Add new FK (→ recipes.id)
    op.create_foreign_key(
        'recipe_versions_recipe_id_fkey',
        'recipe_versions', 'recipes',
        ['recipe_id'], ['id'],
    )
    # 5. Recreate unique constraint with new column name
    op.create_unique_constraint('uq_recipe_version', 'recipe_versions', ['recipe_id', 'version_number'])

    # ── recipe_approvals ──────────────────────────────────────────────────────
    # 1. Drop old FK (→ recipe_drafts.id)
    op.drop_constraint('recipe_approvals_draft_id_fkey', 'recipe_approvals', type_='foreignkey')
    # 2. Rename column
    op.alter_column('recipe_approvals', 'draft_id', new_column_name='recipe_id')
    # 3. Add new FK (→ recipes.id)
    op.create_foreign_key(
        'recipe_approvals_recipe_id_fkey',
        'recipe_approvals', 'recipes',
        ['recipe_id'], ['id'],
        ondelete='CASCADE',
    )


def downgrade() -> None:
    # ── recipe_approvals ──────────────────────────────────────────────────────
    op.drop_constraint('recipe_approvals_recipe_id_fkey', 'recipe_approvals', type_='foreignkey')
    op.alter_column('recipe_approvals', 'recipe_id', new_column_name='draft_id')
    op.create_foreign_key(
        'recipe_approvals_draft_id_fkey',
        'recipe_approvals', 'recipe_drafts',
        ['draft_id'], ['id'],
        ondelete='CASCADE',
    )

    # ── recipe_versions ───────────────────────────────────────────────────────
    op.drop_constraint('uq_recipe_version', 'recipe_versions', type_='unique')
    op.drop_constraint('recipe_versions_recipe_id_fkey', 'recipe_versions', type_='foreignkey')
    op.alter_column('recipe_versions', 'recipe_id', new_column_name='draft_id')
    op.create_foreign_key(
        'recipe_versions_draft_id_fkey',
        'recipe_versions', 'recipe_drafts',
        ['draft_id'], ['id'],
    )
    op.create_unique_constraint('uq_draft_version', 'recipe_versions', ['draft_id', 'version_number'])
