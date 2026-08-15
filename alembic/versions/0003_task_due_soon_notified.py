"""add tasks.last_due_soon_notified_at for due-soon dedupe

Revision ID: 0003_task_due_soon_notified
Revises: 0002_member_user_unique
Create Date: 2026-08-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_task_due_soon_notified"
down_revision: Union[str, Sequence[str], None] = "0002_member_user_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("last_due_soon_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "last_due_soon_notified_at")
