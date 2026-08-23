from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.user import TimestampMixin, utcnow


class Budget(Base, TimestampMixin):
    __tablename__ = "budgets"
    __table_args__ = (
        Index(
            "uq_budgets_family_category",
            "family_id",
            "category",
            unique=True,
            postgresql_where=text("category IS NOT NULL"),
            sqlite_where=text("category IS NOT NULL"),
        ),
        Index(
            "uq_budgets_family_overall",
            "family_id",
            unique=True,
            postgresql_where=text("category IS NULL"),
            sqlite_where=text("category IS NULL"),
        ),
        Index("ix_budgets_family_id", "family_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="EUR")
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"

    budget_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("budgets.id", ondelete="CASCADE"), primary_key=True
    )
    month: Mapped[str] = mapped_column(String, primary_key=True)
    threshold: Mapped[int] = mapped_column(primary_key=True)
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
