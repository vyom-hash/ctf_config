"""Rename exercise tables to challenge

Revision ID: b52865e0e19b
Revises: 4db4b72b6f6f
Create Date: 2026-03-11 00:00:00.000000

Renames:
  exercise_instances       → challenges
  exercise_dependencies    → challenge_dependencies
  exercise_attachments     → challenge_attachments
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b52865e0e19b"
down_revision: Union[str, None] = "4db4b72b6f6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename main table
    op.rename_table("exercise_instances", "challenges")

    # Rename junction table (challenge dependencies)
    op.rename_table("exercise_dependencies", "challenge_dependencies")

    # Rename attachment table
    op.rename_table("exercise_attachments", "challenge_attachments")

    # Update FK constraint names that reference the old table name
    # (PostgreSQL renames indexes automatically on table rename,
    #  but explicit constraint names with the old table name may need updating)
    with op.batch_alter_table("challenge_dependencies") as batch_op:
        batch_op.drop_constraint(
            "exercise_prerequisites_instance_id_fkey", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "exercise_prerequisites_prerequisite_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "challenge_dependencies_instance_id_fkey",
            "challenges",
            ["instance_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "challenge_dependencies_prerequisite_id_fkey",
            "challenges",
            ["prerequisite_id"],
            ["id"],
        )

    with op.batch_alter_table("challenge_attachments") as batch_op:
        batch_op.drop_constraint(
            "instance_attachments_instance_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "challenge_attachments_instance_id_fkey",
            "challenges",
            ["instance_id"],
            ["id"],
        )

    # Update FK constraints on child tables that pointed to exercise_instances
    with op.batch_alter_table("validation_targets") as batch_op:
        batch_op.drop_constraint(
            "objective_flags_instance_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "validation_targets_instance_id_fkey",
            "challenges",
            ["instance_id"],
            ["id"],
        )

    with op.batch_alter_table("guidance_steps") as batch_op:
        batch_op.drop_constraint(
            "assistance_tiers_instance_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "guidance_steps_instance_id_fkey",
            "challenges",
            ["instance_id"],
            ["id"],
        )

    with op.batch_alter_table("point_checkpoints") as batch_op:
        batch_op.drop_constraint(
            "scoring_milestones_instance_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "point_checkpoints_instance_id_fkey",
            "challenges",
            ["instance_id"],
            ["id"],
        )


def downgrade() -> None:
    # Reverse all FK renames first
    with op.batch_alter_table("point_checkpoints") as batch_op:
        batch_op.drop_constraint(
            "point_checkpoints_instance_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "scoring_milestones_instance_id_fkey",
            "exercise_instances",
            ["instance_id"],
            ["id"],
        )

    with op.batch_alter_table("guidance_steps") as batch_op:
        batch_op.drop_constraint(
            "guidance_steps_instance_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "assistance_tiers_instance_id_fkey",
            "exercise_instances",
            ["instance_id"],
            ["id"],
        )

    with op.batch_alter_table("validation_targets") as batch_op:
        batch_op.drop_constraint(
            "validation_targets_instance_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "objective_flags_instance_id_fkey",
            "exercise_instances",
            ["instance_id"],
            ["id"],
        )

    with op.batch_alter_table("challenge_attachments") as batch_op:
        batch_op.drop_constraint(
            "challenge_attachments_instance_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "instance_attachments_instance_id_fkey",
            "exercise_instances",
            ["instance_id"],
            ["id"],
        )

    with op.batch_alter_table("challenge_dependencies") as batch_op:
        batch_op.drop_constraint(
            "challenge_dependencies_instance_id_fkey", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "challenge_dependencies_prerequisite_id_fkey", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "exercise_prerequisites_instance_id_fkey",
            "exercise_instances",
            ["instance_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "exercise_prerequisites_prerequisite_id_fkey",
            "exercise_instances",
            ["prerequisite_id"],
            ["id"],
        )

    op.rename_table("challenge_attachments", "exercise_attachments")
    op.rename_table("challenge_dependencies", "exercise_dependencies")
    op.rename_table("challenges", "exercise_instances")
