"""add shopping_locations and shopping_items.location_id

Revision ID: 0004_shopping_locations
Revises: 0003_task_due_soon_notified
Create Date: 2026-08-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_shopping_locations"
down_revision: Union[str, Sequence[str], None] = "0003_task_due_soon_notified"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_LOCATIONS = (
    "REWE",
    "LIDL",
    "ALDI",
    "Rossmann",
    "DM",
    "African store",
)


def upgrade() -> None:
    op.create_table(
        "shopping_locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("family_id", "name", name="uq_shopping_locations_family_name"),
    )
    op.create_index(op.f("ix_shopping_locations_family_id"), "shopping_locations", ["family_id"], unique=False)

    op.add_column("shopping_items", sa.Column("location_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_shopping_items_location_id"), "shopping_items", ["location_id"], unique=False)
    op.create_foreign_key(
        "fk_shopping_items_location_id",
        "shopping_items",
        "shopping_locations",
        ["location_id"],
        ["id"],
        ondelete="SET NULL",
    )

    conn = op.get_bind()
    families = conn.execute(sa.text("SELECT id FROM families")).fetchall()
    for family in families:
        for i, name in enumerate(DEFAULT_LOCATIONS):
            conn.execute(
                sa.text(
                    "INSERT INTO shopping_locations (id, family_id, name, sort_order, created_at, updated_at) "
                    "VALUES (gen_random_uuid(), :family_id, :name, :sort_order, now(), now())"
                ),
                {"family_id": family[0], "name": name, "sort_order": i},
            )


def downgrade() -> None:
    op.drop_constraint("fk_shopping_items_location_id", "shopping_items", type_="foreignkey")
    op.drop_index(op.f("ix_shopping_items_location_id"), table_name="shopping_items")
    op.drop_column("shopping_items", "location_id")
    op.drop_index(op.f("ix_shopping_locations_family_id"), table_name="shopping_locations")
    op.drop_table("shopping_locations")
