"""Merge restructure_deployment and access_gateway_column heads.

Revision ID: d2e3f4a5b6c7
Revises: 45865f7d5890, c0d1e2f3a4b5
Create Date: 2026-02-26 20:00:00.000000

Merges deployment model restructure and access_gateway column branches.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, None] = ("45865f7d5890", "c0d1e2f3a4b5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
