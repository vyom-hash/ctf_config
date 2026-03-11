"""create resource tier tables

Revision ID: d8352a7d912c
Revises: 96ba9fdfa119
Create Date: 2026-02-26 12:44:02.815643

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd8352a7d912c'
down_revision: Union[str, None] = '96ba9fdfa119'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade():

    # -----------------------------
    # Create resource_tiers table
    # -----------------------------
    op.create_table(
        "resource_tiers",

        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),

        sa.Column("tier_name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),

        sa.Column("cpu_cores", sa.Integer(), nullable=False),
        sa.Column("memory_mb", sa.Integer(), nullable=False),
        sa.Column("storage_gb", sa.Integer(), nullable=False),

        sa.Column(
            "gpu_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),

        sa.Column("provider_type", sa.String(length=100), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=False),
        sa.Column("region", sa.String(length=100), nullable=True),

        # Correct string default (quoted)
        sa.Column(
            "access_scope",
            sa.String(length=20),
            nullable=False,
            server_default="global",
        ),

        sa.Column(
            "owner_tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),

        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),

        sa.Column(
            "extra_metadata",
            postgresql.JSONB(),
            nullable=True,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),

        sa.PrimaryKeyConstraint("id"),

        sa.UniqueConstraint(
            "owner_tenant_id",
            "tier_name",
            name="uq_resource_tier_tenant_name",
        ),

        sa.UniqueConstraint(
            "provider_type",
            "provider_reference",
            name="uq_resource_tier_provider_ref",
        ),
    )

    # ---------------------------------------------
    # Create tenant_resource_tier_limits table
    # ---------------------------------------------
    op.create_table(
        "tenant_resource_tier_limits",

        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),

        sa.Column(
            "resource_tier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("resource_tiers.id", ondelete="CASCADE"),
            primary_key=True,
        ),

        sa.Column(
            "max_instances_allowed",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),

        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def downgrade():

    op.drop_table("tenant_resource_tier_limits")
    op.drop_table("resource_tiers")