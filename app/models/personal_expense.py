from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import TimestampMixin

SOURCE_MANUAL = "manual"
SOURCE_ASSISTANT = "assistant"
CREATE_SOURCE_TYPES = frozenset({SOURCE_MANUAL, SOURCE_ASSISTANT})

PERSONAL_EXPENSE_CATEGORIES = (
    "Dining",
    "Transport",
    "Shopping",
    "Health",
    "Entertainment",
    "Travel",
    "Subscriptions",
    "Other",
)

DEFAULT_PERSONAL_CATEGORY = "Other"
MAX_ACCOUNT_NAME = 40
MAX_MERCHANT = 120
MAX_NOTE = 500


class PersonalExpenseAccount(Base, TimestampMixin):
    __tablename__ = "personal_expense_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_personal_expense_accounts_user_name"),
        Index("ix_personal_expense_accounts_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="EUR")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    expenses: Mapped[list["PersonalExpense"]] = relationship(
        "PersonalExpense", back_populates="account", cascade="all, delete-orphan"
    )


class PersonalExpense(Base, TimestampMixin):
    __tablename__ = "personal_expenses"
    __table_args__ = (
        Index("ix_personal_expenses_account_occurred_at", "account_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("personal_expense_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False, default="EUR")
    category: Mapped[str] = mapped_column(String, nullable=False)
    merchant: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False, default=SOURCE_MANUAL)

    account: Mapped[PersonalExpenseAccount] = relationship(
        "PersonalExpenseAccount", back_populates="expenses"
    )
