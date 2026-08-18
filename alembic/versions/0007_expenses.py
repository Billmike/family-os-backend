"""add expenses ledger and backfill shopping trips

Revision ID: 0007_expenses
Revises: 0006_shopping_sessions
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_expenses"
down_revision: Union[str, Sequence[str], None] = "0006_shopping_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="EUR"),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("merchant", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False, server_default="manual"),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_expenses_family_id", "expenses", ["family_id"])
    op.create_index("ix_expenses_family_occurred_at", "expenses", ["family_id", "occurred_at"])
    op.create_index(
        "uq_expenses_source",
        "expenses",
        ["source_type", "source_id"],
        unique=True,
        postgresql_where=sa.text("source_id IS NOT NULL"),
        sqlite_where=sa.text("source_id IS NOT NULL"),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO expenses (
                id, family_id, amount, currency, category, merchant, note,
                occurred_at, created_by, source_type, source_id, created_at, updated_at
            )
            SELECT
                gen_random_uuid(),
                family_id,
                total_cost,
                currency,
                'Shopping',
                NULL,
                NULL,
                completed_at,
                COALESCE(completed_by, started_by),
                'shopping_session',
                id,
                now(),
                now()
            FROM shopping_sessions
            WHERE status = 'completed'
              AND total_cost IS NOT NULL
              AND completed_at IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("uq_expenses_source", table_name="expenses")
    op.drop_index("ix_expenses_family_occurred_at", table_name="expenses")
    op.drop_index("ix_expenses_family_id", table_name="expenses")
    op.drop_table("expenses")
