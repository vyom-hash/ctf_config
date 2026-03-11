"""create openstack_resource_tier table

Revision ID: 11e974b4f919
Revises: cffc4bf3e166
Create Date: 2026-02-28 19:15:57.369109

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11e974b4f919'
down_revision: Union[str, None] = 'cffc4bf3e166'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    op.create_table(
        "openstack_resource_tier",
        sa.Column("id", sa.String(length=128), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vcpus", sa.Integer(), nullable=False),
        sa.Column("ram", sa.Integer(), nullable=False),
        sa.Column("disk", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Optional helpful index for lookup performance
    op.create_index(
        "ix_openstack_resource_tier_lookup",
        "openstack_resource_tier",
        ["vcpus", "ram", "disk", "region"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_openstack_resource_tier_lookup",
        table_name="openstack_resource_tier",
    )
    op.drop_table("openstack_resource_tier")