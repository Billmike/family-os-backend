"""add shopping_sessions and shopping_session_items

Revision ID: 0006_shopping_sessions
Revises: 0005_push_fail_count
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_shopping_sessions"
down_revision: Union[str, Sequence[str], None] = "0005_push_fail_count"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shopping_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_by", sa.Uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
        sa.Column("total_cost", sa.Numeric(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False, server_default="EUR"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["started_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["completed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shopping_sessions_family_id", "shopping_sessions", ["family_id"])

    op.create_index(
        "uq_shopping_sessions_family_active",
        "shopping_sessions",
        ["family_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "shopping_session_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("quantity", sa.Numeric(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=True),
        sa.Column("location_name", sa.String(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["shopping_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["shopping_locations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shopping_session_items_session_id", "shopping_session_items", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_shopping_session_items_session_id", table_name="shopping_session_items")
    op.drop_table("shopping_session_items")
    op.drop_index("uq_shopping_sessions_family_active", table_name="shopping_sessions")
    op.drop_index("ix_shopping_sessions_family_id", table_name="shopping_sessions")
    op.drop_table("shopping_sessions")
