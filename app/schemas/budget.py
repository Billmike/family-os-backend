from datetime import date, datetime
from decimal import Decimal
from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.expense import EXPENSE_CATEGORIES
from app.schemas.auth import ORMModel

BudgetCategory = Literal[
    "Shopping",
    "Transportation",
    "Housing",
    "Utilities",
    "Dining",
    "Health",
    "Childcare",
    "Other",
]

BudgetState = Literal["ok", "warning", "over"]


class BudgetLineIn(BaseModel):
    category: BudgetCategory | None = None
    amount: Decimal = Field(gt=0)


class BudgetPeriodCreate(BaseModel):
    start_date: date
    end_date: date
    label_month: str | None = None
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    budgets: list[BudgetLineIn] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_range(self) -> "BudgetPeriodCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class BudgetPeriodUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    label_month: str | None = None
    budgets: list[BudgetLineIn] | None = None


class BudgetUpdate(BaseModel):
    amount: Decimal = Field(gt=0)


class BudgetOut(ORMModel):
    id: UUID
    period_id: UUID
    family_id: UUID
    category: str | None
    amount: Decimal
    currency: str
    used: Decimal
    remaining: Decimal
    percent_used: int
    state: BudgetState
    created_at: datetime
    updated_at: datetime


class BudgetPeriodOut(BaseModel):
    id: UUID
    family_id: UUID
    start_date: date
    end_date: date
    label_month: str
    currency: str
    overall: BudgetOut | None
    categories: list[BudgetOut]
    created_at: datetime
    updated_at: datetime


class BudgetPeriodListOut(BaseModel):
    periods: list[BudgetPeriodOut]


class BudgetSummaryOut(BaseModel):
    period_id: UUID
    label_month: str
    start_date: date
    end_date: date
    amount: Decimal
    used: Decimal
    remaining: Decimal
    percent_used: int
    state: BudgetState


assert set(EXPENSE_CATEGORIES) == set(get_args(BudgetCategory))
