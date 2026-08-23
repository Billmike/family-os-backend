"""add budgets and budget alerts

Revision ID: 0010_budgets
Revises: 0009_receipt_shopping_session
Create Date: 2026-08-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_budgets"
down_revision: Union[str, Sequence[str], None] = "0009_receipt_shopping_session"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budgets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="EUR"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_budgets_family_id", "budgets", ["family_id"])
    op.create_index(
        "uq_budgets_family_category",
        "budgets",
        ["family_id", "category"],
        unique=True,
        postgresql_where=sa.text("category IS NOT NULL"),
        sqlite_where=sa.text("category IS NOT NULL"),
    )
    op.create_index(
        "uq_budgets_family_overall",
        "budgets",
        ["family_id"],
        unique=True,
        postgresql_where=sa.text("category IS NULL"),
        sqlite_where=sa.text("category IS NULL"),
    )

    op.create_table(
        "budget_alerts",
        sa.Column("budget_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.String(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["budget_id"], ["budgets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("budget_id", "month", "threshold"),
    )

    op.add_column(
        "notification_preferences",
        sa.Column("budget_alerts", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_column("notification_preferences", "budget_alerts")
    op.drop_table("budget_alerts")
    op.drop_index("uq_budgets_family_overall", table_name="budgets")
    op.drop_index("uq_budgets_family_category", table_name="budgets")
    op.drop_index("ix_budgets_family_id", table_name="budgets")
    op.drop_table("budgets")
