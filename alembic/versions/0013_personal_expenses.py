"""personal expense accounts and user timezone

Revision ID: 0013_personal_expenses
Revises: 0012_budget_groups
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_personal_expenses"
down_revision: Union[str, Sequence[str], None] = "0012_budget_groups"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("timezone", sa.String(), nullable=True))

    op.create_table(
        "personal_expense_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="EUR"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_personal_expense_accounts_user_name"),
    )
    op.create_index("ix_personal_expense_accounts_user_id", "personal_expense_accounts", ["user_id"])

    op.create_table(
        "personal_expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="EUR"),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("merchant", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["personal_expense_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_personal_expenses_account_occurred_at",
        "personal_expenses",
        ["account_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_personal_expenses_account_occurred_at", table_name="personal_expenses")
    op.drop_table("personal_expenses")
    op.drop_index("ix_personal_expense_accounts_user_id", table_name="personal_expense_accounts")
    op.drop_table("personal_expense_accounts")
    op.drop_column("users", "timezone")
