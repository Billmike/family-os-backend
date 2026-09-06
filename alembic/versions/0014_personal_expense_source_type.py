"""personal expense source_type

Revision ID: 0014_personal_expense_source_type
Revises: 0013_personal_expenses
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_personal_expense_source_type"
down_revision: Union[str, Sequence[str], None] = "0013_personal_expenses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "personal_expenses",
        sa.Column("source_type", sa.String(), nullable=False, server_default="manual"),
    )


def downgrade() -> None:
    op.drop_column("personal_expenses", "source_type")
