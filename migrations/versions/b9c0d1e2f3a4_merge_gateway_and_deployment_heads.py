"""Merge gateway and deployment recipe_spec heads.

Revision ID: b9c0d1e2f3a4
Revises: a7b8c9d0e1f2, e2f3a4b5c6d7
Create Date: 2026-02-26 18:00:00.000000

Merges the gateway (runtime_profile, resource_tier) and deployment (recipe_spec, exercises) branches.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = ("a7b8c9d0e1f2", "e2f3a4b5c6d7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
