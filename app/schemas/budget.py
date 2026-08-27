from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.auth import ORMModel

BudgetState = Literal["ok", "warning", "over"]


class BudgetLineIn(BaseModel):
    subcategory_id: UUID
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


class BudgetPeriodCopy(BaseModel):
    start_date: date
    end_date: date
    label_month: str | None = None
    source_period_id: UUID | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "BudgetPeriodCopy":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class BudgetUpdate(BaseModel):
    amount: Decimal = Field(gt=0)


class BudgetOut(ORMModel):
    id: UUID
    period_id: UUID
    family_id: UUID
    subcategory_id: UUID
    subcategory_name: str
    group: str
    amount: Decimal
    currency: str
    used: Decimal
    remaining: Decimal
    percent_used: int
    state: BudgetState
    settled: bool
    settlement_expense_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class BudgetGroupOut(BaseModel):
    group: str
    direction: str
    expected: Decimal
    actual: Decimal
    lines: list[BudgetOut]


class BudgetPeriodSummaryOut(BaseModel):
    income_expected: Decimal
    income_actual: Decimal
    total_expenses_expected: Decimal
    total_expenses_actual: Decimal
    left_over_expected: Decimal
    left_over_actual: Decimal


class BudgetPeriodOut(BaseModel):
    id: UUID
    family_id: UUID
    start_date: date
    end_date: date
    label_month: str
    currency: str
    groups: list[BudgetGroupOut]
    summary: BudgetPeriodSummaryOut
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


class BudgetInsightsMonthOut(BaseModel):
    month: str
    income_expected: Decimal
    income_actual: Decimal
    outflow_expected: Decimal
    outflow_actual: Decimal
    net_expected: Decimal
    net_actual: Decimal
    groups: list[BudgetGroupOut]


class BudgetInsightsOut(BaseModel):
    currency: str
    months: list[BudgetInsightsMonthOut]
