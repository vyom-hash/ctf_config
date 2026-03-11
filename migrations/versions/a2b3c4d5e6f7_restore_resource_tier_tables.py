"""restore resource_tiers, tenant_resource_tier_limits, and openstack_resource_tier tables

These tables were accidentally dropped by f1ffeac1eb61. The app still depends on them.

Revision ID: a2b3c4d5e6f7
Revises: f1ffeac1eb61
Create Date: 2026-03-06 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f1ffeac1eb61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'resource_tiers',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('tier_name', sa.VARCHAR(length=80), nullable=False),
        sa.Column('description', sa.TEXT(), nullable=True),
        sa.Column('cpu_cores', sa.INTEGER(), nullable=False),
        sa.Column('memory_mb', sa.INTEGER(), nullable=False),
        sa.Column('storage_gb', sa.INTEGER(), nullable=False),
        sa.Column('gpu_enabled', sa.BOOLEAN(), server_default=sa.text('false'), nullable=False),
        sa.Column('provider_type', sa.VARCHAR(length=100), nullable=False),
        sa.Column('provider_reference', sa.VARCHAR(length=255), nullable=False),
        sa.Column('region', sa.VARCHAR(length=100), nullable=True),
        sa.Column('access_scope', sa.VARCHAR(length=20), server_default=sa.text("'global'::character varying"), nullable=False),
        sa.Column('owner_tenant_id', sa.UUID(), nullable=True),
        sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
        sa.Column('extra_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id', name='resource_tiers_pkey'),
        sa.UniqueConstraint('owner_tenant_id', 'tier_name', name='uq_resource_tier_tenant_name'),
        sa.UniqueConstraint('provider_type', 'provider_reference', name='uq_resource_tier_provider_ref'),
    )

    op.create_table(
        'tenant_resource_tier_limits',
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('resource_tier_id', sa.UUID(), nullable=False),
        sa.Column('max_instances_allowed', sa.INTEGER(), nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(
            ['resource_tier_id'], ['resource_tiers.id'],
            name='tenant_resource_tier_limits_resource_tier_id_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('tenant_id', 'resource_tier_id', name='tenant_resource_tier_limits_pkey'),
    )

    op.create_table(
        'openstack_resource_tier',
        sa.Column('id', sa.VARCHAR(length=128), nullable=False),
        sa.Column('name', sa.VARCHAR(length=255), nullable=False),
        sa.Column('vcpus', sa.INTEGER(), nullable=False),
        sa.Column('ram', sa.INTEGER(), nullable=False),
        sa.Column('disk', sa.INTEGER(), nullable=False),
        sa.Column('region', sa.VARCHAR(length=100), nullable=True),
        sa.Column('is_active', sa.BOOLEAN(), server_default=sa.text('true'), nullable=False),
        sa.Column('last_synced_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='openstack_resource_tier_pkey'),
    )
    op.create_index(
        'ix_openstack_resource_tier_lookup',
        'openstack_resource_tier',
        ['vcpus', 'ram', 'disk', 'region'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_openstack_resource_tier_lookup', table_name='openstack_resource_tier')
    op.drop_table('openstack_resource_tier')
    op.drop_table('tenant_resource_tier_limits')
    op.drop_table('resource_tiers')
