"""rename_exercise_tables_for_ipr_remediation

Revision ID: 0fc752f7039c
Revises: 71bbfa466b26
Create Date: 2026-03-07 16:09:44.284348

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0fc752f7039c'
down_revision: Union[str, None] = '71bbfa466b26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename Tables
    op.rename_table('instance_attachments', 'exercise_attachments')
    op.rename_table('exercise_prerequisites', 'exercise_dependencies')
    op.rename_table('assistance_tiers', 'guidance_steps')
    op.rename_table('scoring_milestones', 'point_checkpoints')
    op.rename_table('objective_flags', 'validation_targets')
    
    # Drop InstanceSolutions
    op.drop_table('instance_solutions')

    # Rename Columns on exercise_instances
    op.alter_column('exercise_instances', 'infrastructure_template_id', new_column_name='lab_environment_ref')
    op.alter_column('exercise_instances', 'sub_category', new_column_name='progression_mode')
    op.alter_column('exercise_instances', 'isolation_strategy', new_column_name='resource_scope')
    # ### end Alembic commands ###


def downgrade() -> None:
    # Rename Columns on exercise_instances (Revert)
    op.alter_column('exercise_instances', 'lab_environment_ref', new_column_name='infrastructure_template_id')
    op.alter_column('exercise_instances', 'progression_mode', new_column_name='sub_category')
    op.alter_column('exercise_instances', 'resource_scope', new_column_name='isolation_strategy')

    # Recreate InstanceSolutions
    op.create_table('instance_solutions',
    sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
    sa.Column('writeup', sa.TEXT(), autoincrement=False, nullable=True),
    sa.Column('tools', postgresql.ARRAY(sa.TEXT()), autoincrement=False, nullable=False),
    sa.Column('visible_after_solve', sa.BOOLEAN(), autoincrement=False, nullable=False),
    sa.Column('instance_id', sa.UUID(), autoincrement=False, nullable=False),
    sa.ForeignKeyConstraint(['instance_id'], ['exercise_instances.id'], name='instance_solutions_instance_id_fkey'),
    sa.PrimaryKeyConstraint('id', name='instance_solutions_pkey'),
    sa.UniqueConstraint('instance_id', name='instance_solutions_instance_id_key')
    )

    # Rename Tables (Revert)
    op.rename_table('exercise_attachments', 'instance_attachments')
    op.rename_table('exercise_dependencies', 'exercise_prerequisites')
    op.rename_table('guidance_steps', 'assistance_tiers')
    op.rename_table('point_checkpoints', 'scoring_milestones')
    op.rename_table('validation_targets', 'objective_flags')
    # ### end Alembic commands ###
