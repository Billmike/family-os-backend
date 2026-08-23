from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.expense import EXPENSE_CATEGORIES
from app.schemas.auth import ORMModel
from app.schemas.expense import ExpenseCategory, _blank_to_none

ReceiptStatus = Literal["processing", "ready", "failed", "confirmed"]

MAX_MERCHANT = 120
MAX_NOTE = 500
MAX_ITEM_NAME = 200
MAX_UNIT = 40
MAX_TAX_CODE = 8


class ReceiptItemOut(ORMModel):
    id: UUID
    receipt_id: UUID
    position: int
    name: str
    quantity: Decimal | None
    unit: str | None
    unit_price: Decimal | None
    total_price: Decimal
    tax_code: str | None
    is_included: bool
    created_at: datetime
    updated_at: datetime


class ReceiptOut(ORMModel):
    id: UUID
    family_id: UUID
    uploaded_by: UUID
    status: str
    mime_type: str
    byte_size: int
    original_filename: str | None
    category_hint: str | None
    suggested_category: str | None
    merchant: str | None
    purchased_at: datetime | None
    currency: str | None
    subtotal: Decimal | None
    tax_total: Decimal | None
    total: Decimal | None
    totals_mismatch: bool
    model_name: str | None
    error_message: str | None
    expense_id: UUID | None
    shopping_session_id: UUID | None
    items: list[ReceiptItemOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ReceiptItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_ITEM_NAME)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=MAX_UNIT)
    unit_price: Decimal | None = Field(default=None, ge=0)
    total_price: Decimal = Field(ge=0)
    tax_code: str | None = Field(default=None, max_length=MAX_TAX_CODE)
    is_included: bool = True

    @field_validator("name", "unit", "tax_code", mode="before")
    @classmethod
    def strip_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None


class ReceiptConfirm(BaseModel):
    category: ExpenseCategory
    merchant: str | None = Field(default=None, max_length=MAX_MERCHANT)
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    occurred_at: datetime | None = None
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    total: Decimal = Field(gt=0)
    items: list[ReceiptItemInput] = Field(default_factory=list)

    @field_validator("merchant", "note", mode="before")
    @classmethod
    def blank_optional(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str) -> str:
        return value.strip().upper()


assert set(EXPENSE_CATEGORIES) == {
    "Shopping",
    "Transportation",
    "Housing",
    "Utilities",
    "Dining",
    "Health",
    "Childcare",
    "Other",
}
