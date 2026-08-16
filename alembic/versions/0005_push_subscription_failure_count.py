"""add push_subscriptions.failure_count

Revision ID: 0005_push_subscription_failure_count
Revises: 0004_shopping_locations
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_push_subscription_failure_count"
down_revision: Union[str, Sequence[str], None] = "0004_shopping_locations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "push_subscriptions",
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("push_subscriptions", "failure_count")
