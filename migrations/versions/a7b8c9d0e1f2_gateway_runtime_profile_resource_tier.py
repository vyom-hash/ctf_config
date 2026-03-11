"""Gateway: runtime_profile, resource_tier; drop attached_domain.

Revision ID: a7b8c9d0e1f2
Revises: cb7acd4e5032
Create Date: 2026-02-26 16:00:00.000000

- Add runtime_profile and resource_tier to recipe_access_gateways.
- Drop attached_domain from recipe_access_gateways (assigned gateway no longer in recipe).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "cb7acd4e5032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "recipe_access_gateways",
        sa.Column("runtime_profile", sa.String(length=150), nullable=True),
    )
    op.add_column(
        "recipe_access_gateways",
        sa.Column("resource_tier", sa.String(length=100), nullable=True),
    )
    op.drop_column("recipe_access_gateways", "attached_domain")


def downgrade() -> None:
    op.add_column(
        "recipe_access_gateways",
        sa.Column("attached_domain", sa.String(length=100), nullable=True),
    )
    op.drop_column("recipe_access_gateways", "resource_tier")
    op.drop_column("recipe_access_gateways", "runtime_profile")
