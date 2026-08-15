"""partial unique index on linked family members

Revision ID: 0002_member_user_unique
Revises: 0001_initial
Create Date: 2026-08-15
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002_member_user_unique"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_family_members_family_user
        ON family_members (family_id, user_id)
        WHERE user_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("uq_family_members_family_user", table_name="family_members")
