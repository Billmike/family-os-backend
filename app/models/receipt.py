from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.core.database import Base
from app.models.user import TimestampMixin

STATUS_PROCESSING = "processing"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_CONFIRMED = "confirmed"

RECEIPT_STATUSES = (
    STATUS_PROCESSING,
    STATUS_READY,
    STATUS_FAILED,
    STATUS_CONFIRMED,
)


class Receipt(Base, TimestampMixin):
    __tablename__ = "receipts"
    __table_args__ = (
        Index("ix_receipts_family_status", "family_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default=STATUS_PROCESSING)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    mime_type: Mapped[str] = mapped_column(String, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    category_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    suggested_category: Mapped[str | None] = mapped_column(String, nullable=True)
    merchant: Mapped[str | None] = mapped_column(String, nullable=True)
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    currency: Mapped[str | None] = mapped_column(String, nullable=True)
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    tax_total: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    totals_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expense_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True
    )
    shopping_session_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("shopping_sessions.id", ondelete="SET NULL"), nullable=True
    )

    items: Mapped[list["ReceiptItem"]] = relationship(
        "ReceiptItem",
        back_populates="receipt",
        cascade="all, delete-orphan",
        order_by="ReceiptItem.position",
    )


class ReceiptItem(Base, TimestampMixin):
    __tablename__ = "receipt_items"
    __table_args__ = (
        Index("ix_receipt_items_receipt_id", "receipt_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    receipt_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    name: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    total_price: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    tax_code: Mapped[str | None] = mapped_column(String, nullable=True)
    is_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    receipt: Mapped["Receipt"] = relationship("Receipt", back_populates="items")
