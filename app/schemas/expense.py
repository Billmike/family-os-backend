from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.expense import CREATE_SOURCE_TYPES, SOURCE_MANUAL
from app.schemas.auth import ORMModel
from app.schemas.budget import BudgetSummaryOut

MAX_MERCHANT = 120
MAX_NOTE = 500


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class ExpenseCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    subcategory_id: UUID
    merchant: str | None = Field(default=None, max_length=MAX_MERCHANT)
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    occurred_at: datetime | None = None
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    source_type: str = SOURCE_MANUAL

    @field_validator("merchant", "note", mode="before")
    @classmethod
    def blank_optional(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("source_type")
    @classmethod
    def source_type_allowed(cls, value: str) -> str:
        if value not in CREATE_SOURCE_TYPES:
            raise ValueError("source_type must be manual or assistant")
        return value


class ExpenseUpdate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    subcategory_id: UUID | None = None
    merchant: str | None = Field(default=None, max_length=MAX_MERCHANT)
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    occurred_at: datetime | None = None

    @field_validator("merchant", "note", mode="before")
    @classmethod
    def blank_optional(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ExpenseOut(ORMModel):
    id: UUID
    family_id: UUID
    amount: Decimal
    currency: str
    subcategory_id: UUID
    subcategory_name: str
    group: str
    direction: str
    merchant: str | None
    note: str | None
    occurred_at: datetime
    created_by: UUID
    source_type: str
    source_id: UUID | None
    source_item_count: int | None = None
    created_at: datetime
    updated_at: datetime


class CategorySpendOut(BaseModel):
    """Per-subcategory (or group) spend row in monthly aggregation."""

    category: str
    subcategory_id: UUID | None = None
    group: str | None = None
    total: Decimal
    count: int


class MonthlyHouseholdSpendOut(BaseModel):
    month: str
    total: Decimal
    entry_count: int
    average: Decimal
    categories: list[CategorySpendOut] = Field(default_factory=list)


class HouseholdSpendOut(BaseModel):
    currency: str
    current_month: str
    year_to_date_total: Decimal
    months: list[MonthlyHouseholdSpendOut]
    budget: BudgetSummaryOut | None = None
