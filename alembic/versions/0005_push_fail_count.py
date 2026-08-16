"""add push_subscriptions.failure_count

Revision ID: 0005_push_fail_count
Revises: 0004_shopping_locations
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_push_fail_count"
down_revision: Union[str, Sequence[str], None] = "0004_shopping_locations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic's version_num defaults to VARCHAR(32); widen so revision IDs can be descriptive.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")
    op.execute(
        """
        ALTER TABLE push_subscriptions
        ADD COLUMN IF NOT EXISTS failure_count INTEGER NOT NULL DEFAULT 0
        """
    )


def downgrade() -> None:
    op.drop_column("push_subscriptions", "failure_count")
