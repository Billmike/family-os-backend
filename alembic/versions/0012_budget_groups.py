"""budget groups and subcategories

Revision ID: 0012_budget_groups
Revises: 0011_budget_periods
Create Date: 2026-08-27
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "0012_budget_groups"
down_revision: Union[str, Sequence[str], None] = "0011_budget_periods"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Legacy category -> (group, name, role)
_SEED = {
    "Housing": ("Fixed Expense", "Housing", None),
    "Utilities": ("Fixed Expense", "Utilities", None),
    "Childcare": ("Fixed Expense", "Childcare", None),
    "Shopping": ("Fixed Expense", "Groceries", "groceries"),
    "Transportation": ("Fixed Expense", "Transport", None),
    "Dining": ("Variable Expense", "Dining", None),
    "Health": ("Variable Expense", "Health", None),
    "Other": ("Variable Expense", "Other", None),
}


def upgrade() -> None:
    op.create_table(
        "budget_subcategories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("group", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_budget_subcategories_family_id", "budget_subcategories", ["family_id"])
    op.create_index(
        "uq_budget_subcategories_family_group_name",
        "budget_subcategories",
        ["family_id", "group", "name"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
        sqlite_where=sa.text("archived_at IS NULL"),
    )

    conn = op.get_bind()
    families = conn.execute(sa.text("SELECT id FROM families")).fetchall()
    subcategory_ids: dict[tuple[str, str], str] = {}

    for (family_id,) in families:
        family_key = str(family_id)
        for sort_order, (legacy, (group, name, role)) in enumerate(_SEED.items()):
            sub_id = str(uuid4())
            conn.execute(
                sa.text(
                    """
                    INSERT INTO budget_subcategories
                        (id, family_id, "group", name, sort_order, role, created_at, updated_at)
                    VALUES
                        (:id, :family_id, :group, :name, :sort_order, :role, now(), now())
                    """
                ),
                {
                    "id": sub_id,
                    "family_id": family_key,
                    "group": group,
                    "name": name,
                    "sort_order": sort_order,
                    "role": role,
                },
            )
            subcategory_ids[(family_key, legacy)] = sub_id

    op.add_column("expenses", sa.Column("subcategory_id", sa.Uuid(), nullable=True))

    expenses = conn.execute(sa.text("SELECT id, family_id, category FROM expenses")).fetchall()
    for expense_id, family_id, category in expenses:
        key = (str(family_id), category)
        sub_id = subcategory_ids.get(key)
        if sub_id is None:
            # Fallback: Variable Expense / Other for unknown categories
            fallback = subcategory_ids.get((str(family_id), "Other"))
            if fallback is None:
                continue
            sub_id = fallback
        conn.execute(
            sa.text("UPDATE expenses SET subcategory_id = :sub_id WHERE id = :id"),
            {"sub_id": sub_id, "id": str(expense_id)},
        )

    # Any remaining nulls get Variable/Other per family
    remaining = conn.execute(
        sa.text("SELECT id, family_id FROM expenses WHERE subcategory_id IS NULL")
    ).fetchall()
    for expense_id, family_id in remaining:
        fallback = subcategory_ids.get((str(family_id), "Other"))
        if fallback is None:
            continue
        conn.execute(
            sa.text("UPDATE expenses SET subcategory_id = :sub_id WHERE id = :id"),
            {"sub_id": fallback, "id": str(expense_id)},
        )

    op.alter_column("expenses", "subcategory_id", nullable=False)
    op.create_foreign_key(
        "fk_expenses_subcategory_id",
        "expenses",
        "budget_subcategories",
        ["subcategory_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_expenses_subcategory_id", "expenses", ["subcategory_id"])
    op.drop_column("expenses", "category")

    # Reshape budgets: add subcategory_id, drop overall rows and category
    op.add_column("budgets", sa.Column("subcategory_id", sa.Uuid(), nullable=True))

    # Join budgets -> periods to get family_id for mapping
    budget_rows = conn.execute(
        sa.text(
            """
            SELECT b.id, b.category, bp.family_id
            FROM budgets b
            JOIN budget_periods bp ON bp.id = b.period_id
            """
        )
    ).fetchall()

    for budget_id, category, family_id in budget_rows:
        if category is None:
            conn.execute(sa.text("DELETE FROM budgets WHERE id = :id"), {"id": str(budget_id)})
            continue
        sub_id = subcategory_ids.get((str(family_id), category))
        if sub_id is None:
            conn.execute(sa.text("DELETE FROM budgets WHERE id = :id"), {"id": str(budget_id)})
            continue
        conn.execute(
            sa.text("UPDATE budgets SET subcategory_id = :sub_id WHERE id = :id"),
            {"sub_id": sub_id, "id": str(budget_id)},
        )

    # Drop any leftover overall / unmapped rows
    conn.execute(sa.text("DELETE FROM budgets WHERE subcategory_id IS NULL"))

    op.alter_column("budgets", "subcategory_id", nullable=False)
    op.create_foreign_key(
        "fk_budgets_subcategory_id",
        "budgets",
        "budget_subcategories",
        ["subcategory_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_budgets_subcategory_id", "budgets", ["subcategory_id"])

    op.drop_index("uq_budgets_period_category", table_name="budgets")
    op.drop_index("uq_budgets_period_overall", table_name="budgets")
    op.drop_column("budgets", "category")
    op.create_index(
        "uq_budgets_period_subcategory",
        "budgets",
        ["period_id", "subcategory_id"],
        unique=True,
    )


def downgrade() -> None:
    op.add_column("budgets", sa.Column("category", sa.String(), nullable=True))

    conn = op.get_bind()
    # Best-effort reverse: map subcategory name back via seed reverse map
    reverse = {name: legacy for legacy, (_, name, _) in _SEED.items()}
    rows = conn.execute(
        sa.text(
            """
            SELECT b.id, s.name
            FROM budgets b
            JOIN budget_subcategories s ON s.id = b.subcategory_id
            """
        )
    ).fetchall()
    for budget_id, name in rows:
        category = reverse.get(name, "Other")
        conn.execute(
            sa.text("UPDATE budgets SET category = :cat WHERE id = :id"),
            {"cat": category, "id": str(budget_id)},
        )

    op.drop_index("uq_budgets_period_subcategory", table_name="budgets")
    op.drop_constraint("fk_budgets_subcategory_id", "budgets", type_="foreignkey")
    op.drop_index("ix_budgets_subcategory_id", table_name="budgets")
    op.drop_column("budgets", "subcategory_id")
    op.create_index(
        "uq_budgets_period_category",
        "budgets",
        ["period_id", "category"],
        unique=True,
        postgresql_where=sa.text("category IS NOT NULL"),
        sqlite_where=sa.text("category IS NOT NULL"),
    )
    op.create_index(
        "uq_budgets_period_overall",
        "budgets",
        ["period_id"],
        unique=True,
        postgresql_where=sa.text("category IS NULL"),
        sqlite_where=sa.text("category IS NULL"),
    )

    op.add_column("expenses", sa.Column("category", sa.String(), nullable=True))
    exp_rows = conn.execute(
        sa.text(
            """
            SELECT e.id, s.name
            FROM expenses e
            JOIN budget_subcategories s ON s.id = e.subcategory_id
            """
        )
    ).fetchall()
    for expense_id, name in exp_rows:
        category = reverse.get(name, "Other")
        conn.execute(
            sa.text("UPDATE expenses SET category = :cat WHERE id = :id"),
            {"cat": category, "id": str(expense_id)},
        )
    op.execute(sa.text("UPDATE expenses SET category = 'Other' WHERE category IS NULL"))
    op.alter_column("expenses", "category", nullable=False)
    op.drop_constraint("fk_expenses_subcategory_id", "expenses", type_="foreignkey")
    op.drop_index("ix_expenses_subcategory_id", table_name="expenses")
    op.drop_column("expenses", "subcategory_id")

    op.drop_index("uq_budget_subcategories_family_group_name", table_name="budget_subcategories")
    op.drop_index("ix_budget_subcategories_family_id", table_name="budget_subcategories")
    op.drop_table("budget_subcategories")
