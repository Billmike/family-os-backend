"""add shopping_session_id to receipts

Revision ID: 0009_receipt_shopping_session
Revises: 0008_receipts
Create Date: 2026-08-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_receipt_shopping_session"
down_revision: Union[str, Sequence[str], None] = "0008_receipts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "receipts",
        sa.Column("shopping_session_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_receipts_shopping_session_id",
        "receipts",
        "shopping_sessions",
        ["shopping_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_receipts_shopping_session_id",
        "receipts",
        ["shopping_session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_receipts_shopping_session_id", table_name="receipts")
    op.drop_constraint("fk_receipts_shopping_session_id", "receipts", type_="foreignkey")
    op.drop_column("receipts", "shopping_session_id")
