from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.personal_expense import (
    CREATE_SOURCE_TYPES,
    DEFAULT_PERSONAL_CATEGORY,
    MAX_ACCOUNT_NAME,
    MAX_MERCHANT,
    MAX_NOTE,
    PERSONAL_EXPENSE_CATEGORIES,
    SOURCE_MANUAL,
)
from app.schemas.auth import ORMModel

_CATEGORY_SET = frozenset(PERSONAL_EXPENSE_CATEGORIES)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class PersonalAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_ACCOUNT_NAME)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name is required")
        return stripped

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("timezone", mode="before")
    @classmethod
    def blank_timezone(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class PersonalAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=MAX_ACCOUNT_NAME)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name is required")
        return stripped

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().upper()


class PersonalAccountOut(ORMModel):
    id: UUID
    name: str
    currency: str
    sort_order: int
    current_month_total: Decimal
    current_month_count: int
    created_at: datetime
    updated_at: datetime


class PersonalAccountListOut(BaseModel):
    timezone: str
    current_month: str
    current_month_total: Decimal
    current_month_count: int
    currency: str
    accounts: list[PersonalAccountOut]


class PersonalExpenseCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    category: str = Field(default=DEFAULT_PERSONAL_CATEGORY)
    merchant: str | None = Field(default=None, max_length=MAX_MERCHANT)
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    occurred_at: datetime | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source_type: str = SOURCE_MANUAL

    @field_validator("merchant", "note", mode="before")
    @classmethod
    def blank_optional(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str) -> str:
        stripped = value.strip()
        if stripped not in _CATEGORY_SET:
            raise ValueError("Invalid category")
        return stripped

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().upper()

    @field_validator("source_type")
    @classmethod
    def source_type_allowed(cls, value: str) -> str:
        if value not in CREATE_SOURCE_TYPES:
            raise ValueError("source_type must be manual or assistant")
        return value


class PersonalExpenseUpdate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0)
    category: str | None = None
    merchant: str | None = Field(default=None, max_length=MAX_MERCHANT)
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    occurred_at: datetime | None = None

    @field_validator("merchant", "note", mode="before")
    @classmethod
    def blank_optional(cls, value: str | None) -> str | None:
        return _blank_to_none(value)

    @field_validator("category")
    @classmethod
    def known_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if stripped not in _CATEGORY_SET:
            raise ValueError("Invalid category")
        return stripped


class PersonalExpenseOut(ORMModel):
    id: UUID
    account_id: UUID
    amount: Decimal
    currency: str
    category: str
    merchant: str | None
    note: str | None
    occurred_at: datetime
    source_type: str
    created_at: datetime
    updated_at: datetime
