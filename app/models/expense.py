from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import TimestampMixin

SOURCE_MANUAL = "manual"
SOURCE_SHOPPING_SESSION = "shopping_session"

CATEGORY_SHOPPING = "Shopping"
CATEGORY_TRANSPORTATION = "Transportation"
CATEGORY_HOUSING = "Housing"
CATEGORY_UTILITIES = "Utilities"
CATEGORY_DINING = "Dining"
CATEGORY_HEALTH = "Health"
CATEGORY_CHILDCARE = "Childcare"
CATEGORY_OTHER = "Other"

EXPENSE_CATEGORIES = (
    CATEGORY_SHOPPING,
    CATEGORY_TRANSPORTATION,
    CATEGORY_HOUSING,
    CATEGORY_UTILITIES,
    CATEGORY_DINING,
    CATEGORY_HEALTH,
    CATEGORY_CHILDCARE,
    CATEGORY_OTHER,
)


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"
    __table_args__ = (
        Index("ix_expenses_family_occurred_at", "family_id", "occurred_at"),
        Index(
            "uq_expenses_source",
            "source_type",
            "source_id",
            unique=True,
            postgresql_where=text("source_id IS NOT NULL"),
            sqlite_where=text("source_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="EUR")
    category: Mapped[str] = mapped_column(String, nullable=False)
    merchant: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False, default=SOURCE_MANUAL)
    source_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
