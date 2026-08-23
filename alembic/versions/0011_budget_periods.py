"""reshape budgets into dated periods

Revision ID: 0011_budget_periods
Revises: 0010_budgets
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_budget_periods"
down_revision: Union[str, Sequence[str], None] = "0010_budgets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "budget_periods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("label_month", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="EUR"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_budget_periods_family_id", "budget_periods", ["family_id"])
    op.create_index(
        "ix_budget_periods_family_dates",
        "budget_periods",
        ["family_id", "start_date", "end_date"],
    )

    op.drop_table("budget_alerts")

    op.create_table(
        "budgets_new",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["period_id"], ["budget_periods.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    conn = op.get_bind()
    families = conn.execute(
        sa.text("SELECT DISTINCT family_id, currency, created_by FROM budgets")
    ).fetchall()

    import uuid
    from calendar import monthrange
    from datetime import date, datetime, timezone

    for family_id, currency, created_by in families:
        # Use UTC calendar month for backfill (timezone-aware conversion needs app code)
        today = datetime.now(timezone.utc).date()
        start = date(today.year, today.month, 1)
        end = date(today.year, today.month, monthrange(today.year, today.month)[1])
        label_month = f"{today.year:04d}-{today.month:02d}"
        period_id = uuid.uuid4()
        conn.execute(
            sa.text(
                """
                INSERT INTO budget_periods
                  (id, family_id, start_date, end_date, label_month, currency, created_by)
                VALUES
                  (:id, :family_id, :start_date, :end_date, :label_month, :currency, :created_by)
                """
            ),
            {
                "id": period_id,
                "family_id": family_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "label_month": label_month,
                "currency": currency or "EUR",
                "created_by": created_by,
            },
        )
        old_rows = conn.execute(
            sa.text(
                "SELECT id, category, amount, created_at, updated_at FROM budgets WHERE family_id = :fid"
            ),
            {"fid": family_id},
        ).fetchall()
        for row_id, category, amount, created_at, updated_at in old_rows:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO budgets_new (id, period_id, category, amount, created_at, updated_at)
                    VALUES (:id, :period_id, :category, :amount, :created_at, :updated_at)
                    """
                ),
                {
                    "id": row_id,
                    "period_id": period_id,
                    "category": category,
                    "amount": amount,
                    "created_at": created_at,
                    "updated_at": updated_at,
                },
            )

    op.drop_index("uq_budgets_family_overall", table_name="budgets")
    op.drop_index("uq_budgets_family_category", table_name="budgets")
    op.drop_index("ix_budgets_family_id", table_name="budgets")
    op.drop_table("budgets")
    op.rename_table("budgets_new", "budgets")

    op.create_index("ix_budgets_period_id", "budgets", ["period_id"])
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

    op.create_table(
        "budget_alerts",
        sa.Column("budget_id", sa.Uuid(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["budget_id"], ["budgets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("budget_id", "threshold"),
    )


def downgrade() -> None:
    op.drop_table("budget_alerts")
    op.drop_index("uq_budgets_period_overall", table_name="budgets")
    op.drop_index("uq_budgets_period_category", table_name="budgets")
    op.drop_index("ix_budgets_period_id", table_name="budgets")

    op.create_table(
        "budgets_old",
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

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT b.id, p.family_id, b.category, b.amount, p.currency, p.created_by,
                   b.created_at, b.updated_at
            FROM budgets b
            JOIN budget_periods p ON p.id = b.period_id
            """
        )
    ).fetchall()
    for row in rows:
        conn.execute(
            sa.text(
                """
                INSERT INTO budgets_old
                  (id, family_id, category, amount, currency, created_by, created_at, updated_at)
                VALUES
                  (:id, :family_id, :category, :amount, :currency, :created_by, :created_at, :updated_at)
                """
            ),
            {
                "id": row[0],
                "family_id": row[1],
                "category": row[2],
                "amount": row[3],
                "currency": row[4],
                "created_by": row[5],
                "created_at": row[6],
                "updated_at": row[7],
            },
        )

    op.drop_table("budgets")
    op.rename_table("budgets_old", "budgets")
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

    op.drop_index("ix_budget_periods_family_dates", table_name="budget_periods")
    op.drop_index("ix_budget_periods_family_id", table_name="budget_periods")
    op.drop_table("budget_periods")

    op.create_table(
        "budget_alerts",
        sa.Column("budget_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.String(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["budget_id"], ["budgets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("budget_id", "month", "threshold"),
    )
