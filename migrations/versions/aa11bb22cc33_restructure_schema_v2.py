"""Restructure schema v2: rename/add/drop fields across deployments, recipe, challenges.

Revision ID: aa11bb22cc33
Revises: b5f217e199e6
Create Date: 2026-03-12 12:00:00.000000

Changes:
  deployments: add description, drop member_ids, add participant_id, rename access_mode→access_method
  recipe_network_profiles: drop segmentation_strategy, default_subnet_mask
  recipe_network_domains: rename public_ingress_enabled→enable_egress, domain_key→name,
                          drop allow_inter_domain_routing, add domain_size
  recipe_workload_units: drop functional_role, rename unit_key→name,
                         network_position_index→allocation_index,
                         connectivity_profile→access_method, agent_enabled→unit_control_active,
                         add description
  recipe_automation_profiles: rename all 3 reference columns
  recipe_access_gateways: add secure_shell, egress_ip
  recipe_gateway_exposure_rules: add rule_name, rule_desc, ext_port,
                                  rename transport_protocol→proto,
                                  internal_port→int_port, unit_key→wl_unit
  challenges: drop experience_mode, add type, rename lab_environment_ref→verification_automation
  guidance_steps→hints: rename table + restructure columns, drop guidancetype enum
  point_checkpoints→objectives: rename table + rename columns
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "aa11bb22cc33"
down_revision: Union[str, None] = "b5f217e199e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── deployments ──────────────────────────────────────────────────────────
    op.add_column("deployments", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("deployments", sa.Column("participant_id", sa.UUID(as_uuid=True), nullable=True))
    op.drop_column("deployments", "member_ids")
    op.alter_column("deployments", "access_mode",
                    new_column_name="access_method",
                    existing_type=sa.String(50), nullable=True)

    # ── recipe_network_profiles ───────────────────────────────────────────────
    op.drop_column("recipe_network_profiles", "segmentation_strategy")
    op.drop_column("recipe_network_profiles", "default_subnet_mask")

    # ── recipe_network_domains ────────────────────────────────────────────────
    op.alter_column("recipe_network_domains", "domain_key",
                    new_column_name="name",
                    existing_type=sa.String(100), nullable=False)
    op.alter_column("recipe_network_domains", "public_ingress_enabled",
                    new_column_name="enable_egress",
                    existing_type=sa.Boolean(), nullable=False)
    op.drop_column("recipe_network_domains", "allow_inter_domain_routing")
    op.add_column("recipe_network_domains", sa.Column("domain_size", sa.Integer(), nullable=True))

    # ── recipe_workload_units ─────────────────────────────────────────────────
    op.alter_column("recipe_workload_units", "unit_key",
                    new_column_name="name",
                    existing_type=sa.String(100), nullable=False)
    op.drop_column("recipe_workload_units", "functional_role")
    op.alter_column("recipe_workload_units", "network_position_index",
                    new_column_name="allocation_index",
                    existing_type=sa.Integer(), nullable=True)
    op.alter_column("recipe_workload_units", "connectivity_profile",
                    new_column_name="access_method",
                    existing_type=sa.String(100), nullable=True)
    op.alter_column("recipe_workload_units", "agent_enabled",
                    new_column_name="unit_control_active",
                    existing_type=sa.Boolean(), nullable=False)
    op.add_column("recipe_workload_units", sa.Column("description", sa.Text(), nullable=True))

    # ── recipe_automation_profiles ────────────────────────────────────────────
    op.alter_column("recipe_automation_profiles", "bootstrap_reference",
                    new_column_name="bootstrap_automation",
                    existing_type=sa.Text(), nullable=True)
    op.alter_column("recipe_automation_profiles", "initialization_reference",
                    new_column_name="preflight_automation",
                    existing_type=sa.Text(), nullable=True)
    op.alter_column("recipe_automation_profiles", "health_check_reference",
                    new_column_name="heartbeat_automation",
                    existing_type=sa.Text(), nullable=True)

    # ── recipe_access_gateways ────────────────────────────────────────────────
    op.add_column("recipe_access_gateways",
                  sa.Column("secure_shell", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("recipe_access_gateways",
                  sa.Column("egress_ip", sa.Boolean(), nullable=False, server_default="false"))

    # ── recipe_gateway_exposure_rules ─────────────────────────────────────────
    op.alter_column("recipe_gateway_exposure_rules", "unit_key",
                    new_column_name="wl_unit",
                    existing_type=sa.String(100), nullable=True)
    op.alter_column("recipe_gateway_exposure_rules", "internal_port",
                    new_column_name="int_port",
                    existing_type=sa.Integer(), nullable=True)
    op.alter_column("recipe_gateway_exposure_rules", "transport_protocol",
                    new_column_name="proto",
                    existing_type=sa.String(20), nullable=True)
    op.add_column("recipe_gateway_exposure_rules",
                  sa.Column("rule_name", sa.String(100), nullable=True))
    op.add_column("recipe_gateway_exposure_rules",
                  sa.Column("rule_desc", sa.Text(), nullable=True))
    op.add_column("recipe_gateway_exposure_rules",
                  sa.Column("ext_port", sa.Integer(), nullable=True))

    # ── challenges ────────────────────────────────────────────────────────────
    op.drop_column("challenges", "experience_mode")
    op.add_column("challenges", sa.Column("type", sa.String(50), nullable=True))
    op.alter_column("challenges", "lab_environment_ref",
                    new_column_name="verification_automation",
                    existing_type=sa.String(50), nullable=True,
                    type_=sa.String(255))

    # ── guidance_steps → hints ────────────────────────────────────────────────
    # Drop columns that don't exist in the new hints table
    op.drop_column("guidance_steps", "order")
    op.drop_column("guidance_steps", "type")
    op.drop_column("guidance_steps", "unlock_after_minutes")
    # Rename remaining columns
    op.alter_column("guidance_steps", "content",
                    new_column_name="hint",
                    existing_type=sa.Text(), nullable=False)
    op.alter_column("guidance_steps", "penalty_points",
                    new_column_name="points_impacted",
                    existing_type=sa.Integer(), nullable=False)
    # Rename the table
    op.rename_table("guidance_steps", "hints")
    # Drop the now-unused guidancetype enum
    op.execute("DROP TYPE IF EXISTS guidancetype")

    # ── point_checkpoints → objectives ────────────────────────────────────────
    op.alter_column("point_checkpoints", "label",
                    new_column_name="goal",
                    existing_type=sa.String(120), nullable=False)
    op.alter_column("point_checkpoints", "points",
                    new_column_name="points_impacted",
                    existing_type=sa.Integer(), nullable=False)
    op.rename_table("point_checkpoints", "objectives")


def downgrade() -> None:
    # objectives → point_checkpoints
    op.rename_table("objectives", "point_checkpoints")
    op.alter_column("point_checkpoints", "points_impacted",
                    new_column_name="points",
                    existing_type=sa.Integer(), nullable=False)
    op.alter_column("point_checkpoints", "goal",
                    new_column_name="label",
                    existing_type=sa.String(120), nullable=False)

    # hints → guidance_steps
    op.rename_table("hints", "guidance_steps")
    op.alter_column("guidance_steps", "points_impacted",
                    new_column_name="penalty_points",
                    existing_type=sa.Integer(), nullable=False)
    op.alter_column("guidance_steps", "hint",
                    new_column_name="content",
                    existing_type=sa.Text(), nullable=False)
    op.add_column("guidance_steps",
                  sa.Column("unlock_after_minutes", sa.Integer(), nullable=True))
    # Re-creating enum and column is complex; omit for simplicity
    op.add_column("guidance_steps",
                  sa.Column("order", sa.Integer(), nullable=False, server_default="0"))

    # challenges
    op.alter_column("challenges", "verification_automation",
                    new_column_name="lab_environment_ref",
                    existing_type=sa.String(255), nullable=True,
                    type_=sa.String(50))
    op.drop_column("challenges", "type")
    op.add_column("challenges",
                  sa.Column("experience_mode", sa.String(50), nullable=True))

    # recipe_gateway_exposure_rules
    op.drop_column("recipe_gateway_exposure_rules", "ext_port")
    op.drop_column("recipe_gateway_exposure_rules", "rule_desc")
    op.drop_column("recipe_gateway_exposure_rules", "rule_name")
    op.alter_column("recipe_gateway_exposure_rules", "proto",
                    new_column_name="transport_protocol",
                    existing_type=sa.String(20), nullable=True)
    op.alter_column("recipe_gateway_exposure_rules", "int_port",
                    new_column_name="internal_port",
                    existing_type=sa.Integer(), nullable=True)
    op.alter_column("recipe_gateway_exposure_rules", "wl_unit",
                    new_column_name="unit_key",
                    existing_type=sa.String(100), nullable=True)

    # recipe_access_gateways
    op.drop_column("recipe_access_gateways", "egress_ip")
    op.drop_column("recipe_access_gateways", "secure_shell")

    # recipe_automation_profiles
    op.alter_column("recipe_automation_profiles", "heartbeat_automation",
                    new_column_name="health_check_reference",
                    existing_type=sa.Text(), nullable=True)
    op.alter_column("recipe_automation_profiles", "preflight_automation",
                    new_column_name="initialization_reference",
                    existing_type=sa.Text(), nullable=True)
    op.alter_column("recipe_automation_profiles", "bootstrap_automation",
                    new_column_name="bootstrap_reference",
                    existing_type=sa.Text(), nullable=True)

    # recipe_workload_units
    op.drop_column("recipe_workload_units", "description")
    op.alter_column("recipe_workload_units", "unit_control_active",
                    new_column_name="agent_enabled",
                    existing_type=sa.Boolean(), nullable=False)
    op.alter_column("recipe_workload_units", "access_method",
                    new_column_name="connectivity_profile",
                    existing_type=sa.String(100), nullable=True)
    op.alter_column("recipe_workload_units", "allocation_index",
                    new_column_name="network_position_index",
                    existing_type=sa.Integer(), nullable=True)
    op.add_column("recipe_workload_units",
                  sa.Column("functional_role", sa.String(100), nullable=True))
    op.alter_column("recipe_workload_units", "name",
                    new_column_name="unit_key",
                    existing_type=sa.String(100), nullable=False)

    # recipe_network_domains
    op.drop_column("recipe_network_domains", "domain_size")
    op.add_column("recipe_network_domains",
                  sa.Column("allow_inter_domain_routing", sa.Boolean(),
                            nullable=False, server_default="false"))
    op.alter_column("recipe_network_domains", "enable_egress",
                    new_column_name="public_ingress_enabled",
                    existing_type=sa.Boolean(), nullable=False)
    op.alter_column("recipe_network_domains", "name",
                    new_column_name="domain_key",
                    existing_type=sa.String(100), nullable=False)

    # recipe_network_profiles
    op.add_column("recipe_network_profiles",
                  sa.Column("default_subnet_mask", sa.Integer(),
                            nullable=False, server_default="24"))
    op.add_column("recipe_network_profiles",
                  sa.Column("segmentation_strategy", sa.String(50),
                            nullable=False, server_default="single_net"))

    # deployments
    op.alter_column("deployments", "access_method",
                    new_column_name="access_mode",
                    existing_type=sa.String(50), nullable=True)
    op.drop_column("deployments", "participant_id")
    op.add_column("deployments",
                  sa.Column("member_ids",
                            sa.ARRAY(sa.UUID(as_uuid=True)),
                            nullable=False, server_default="{}"))
    op.drop_column("deployments", "description")
