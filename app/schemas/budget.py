from datetime import datetime
from decimal import Decimal
from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

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


class BudgetCreate(BaseModel):
    category: BudgetCategory | None = None
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="EUR", min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, value: str) -> str:
        return value.strip().upper()


class BudgetUpdate(BaseModel):
    amount: Decimal = Field(gt=0)


class BudgetOut(ORMModel):
    id: UUID
    family_id: UUID
    category: str | None
    amount: Decimal
    currency: str
    month: str
    used: Decimal
    remaining: Decimal
    percent_used: int
    state: BudgetState
    created_at: datetime
    updated_at: datetime


class BudgetListOut(BaseModel):
    month: str
    currency: str
    overall: BudgetOut | None
    categories: list[BudgetOut]


class BudgetSummaryOut(BaseModel):
    amount: Decimal
    used: Decimal
    remaining: Decimal
    percent_used: int
    state: BudgetState


assert set(EXPENSE_CATEGORIES) == set(get_args(BudgetCategory))
