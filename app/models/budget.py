from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import TimestampMixin, utcnow


class BudgetPeriod(Base, TimestampMixin):
    __tablename__ = "budget_periods"
    __table_args__ = (
        Index("ix_budget_periods_family_id", "family_id"),
        Index("ix_budget_periods_family_dates", "family_id", "start_date", "end_date"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    label_month: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="EUR")
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    budgets: Mapped[list["Budget"]] = relationship(
        "Budget", back_populates="period", cascade="all, delete-orphan"
    )


class Budget(Base, TimestampMixin):
    __tablename__ = "budgets"
    __table_args__ = (
        Index(
            "uq_budgets_period_subcategory",
            "period_id",
            "subcategory_id",
            unique=True,
        ),
        Index("ix_budgets_period_id", "period_id"),
        Index("ix_budgets_subcategory_id", "subcategory_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    period_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("budget_periods.id", ondelete="CASCADE"), nullable=False
    )
    subcategory_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("budget_subcategories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric, nullable=False)

    period: Mapped[BudgetPeriod] = relationship("BudgetPeriod", back_populates="budgets")


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"

    budget_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("budgets.id", ondelete="CASCADE"), primary_key=True
    )
    threshold: Mapped[int] = mapped_column(primary_key=True)
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
