"""Add ExerciseInstance and related tables

Revision ID: 4f6e3d2a1bcd
Revises: 96ba9fdfa119
Create Date: 2026-02-26 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "4f6e3d2a1bcd"
down_revision: Union[str, None] = "96ba9fdfa119"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exercise_instances",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("instance_slug", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column(
            "domain_tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "difficulty",
            sa.Enum("beginner", "intermediate", "advanced", name="difficulty"),
            nullable=False,
        ),
        sa.Column("reward_points", sa.Integer(), nullable=False),
        sa.Column(
            "health_status",
            sa.Enum(
                "draft",
                "verified",
                "degraded",
                "retired",
                name="healthstatus",
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("infrastructure_template_id", sa.String(length=50), nullable=True),
        sa.Column(
            "scoring_type",
            sa.Enum("flat", "decay", "milestone", name="scoringtype"),
            nullable=False,
            server_default="flat",
        ),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("instance_slug"),
    )
    op.create_index("ix_ei_slug", "exercise_instances", ["instance_slug"])
    op.create_index("ix_ei_health_status", "exercise_instances", ["health_status"])
    op.create_index("ix_ei_difficulty", "exercise_instances", ["difficulty"])
    op.create_index("ix_ei_deleted_at", "exercise_instances", ["deleted_at"])
    op.create_index("ix_ei_created_by", "exercise_instances", ["created_by"])
    op.create_index("ix_ei_created_at", "exercise_instances", ["created_at"])

    op.create_table(
        "objective_flags",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("flag_template", sa.String(length=255), nullable=False),
        sa.Column("custom_evaluator", sa.Text(), nullable=True),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"], ["exercise_instances.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "assistance_tiers",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "conceptual",
                "directional",
                "procedural",
                name="hinttype",
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("penalty_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unlock_after_minutes", sa.Integer(), nullable=True),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"], ["exercise_instances.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "instance_attachments",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "visibility",
            sa.Enum("public", "on_solve", name="attachmentvisibility"),
            nullable=False,
            server_default="public",
        ),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"], ["exercise_instances.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "instance_solutions",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("writeup", sa.Text(), nullable=True),
        sa.Column(
            "tools",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("visible_after_solve", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("instance_id", sa.UUID(), nullable=False, unique=True),
        sa.ForeignKeyConstraint(
            ["instance_id"], ["exercise_instances.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "scoring_milestones",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"], ["exercise_instances.id"], ondelete="CASCADE"
        ),
    )

    op.create_table(
        "exercise_prerequisites",
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.Column("prerequisite_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instance_id"], ["exercise_instances.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["prerequisite_id"], ["exercise_instances.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("instance_id", "prerequisite_id"),
    )


def downgrade() -> None:
    op.drop_table("exercise_prerequisites")
    op.drop_table("scoring_milestones")
    op.drop_table("instance_solutions")
    op.drop_table("instance_attachments")
    op.drop_table("assistance_tiers")
    op.drop_table("objective_flags")
    op.drop_index("ix_ei_created_at", table_name="exercise_instances")
    op.drop_index("ix_ei_created_by", table_name="exercise_instances")
    op.drop_index("ix_ei_deleted_at", table_name="exercise_instances")
    op.drop_index("ix_ei_difficulty", table_name="exercise_instances")
    op.drop_index("ix_ei_health_status", table_name="exercise_instances")
    op.drop_index("ix_ei_slug", table_name="exercise_instances")
    op.drop_table("exercise_instances")

    sa.Enum(name="difficulty").drop(op.get_bind(), checkfirst=False)
    sa.Enum(name="healthstatus").drop(op.get_bind(), checkfirst=False)
    sa.Enum(name="scoringtype").drop(op.get_bind(), checkfirst=False)
    sa.Enum(name="hinttype").drop(op.get_bind(), checkfirst=False)
    sa.Enum(name="attachmentvisibility").drop(op.get_bind(), checkfirst=False)

