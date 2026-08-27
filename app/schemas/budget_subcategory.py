from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.budget_group import BUDGET_GROUPS, BudgetGroup
from app.schemas.auth import ORMModel


class BudgetSubcategoryCreate(BaseModel):
    group: BudgetGroup
    name: str = Field(min_length=1, max_length=120)
    sort_order: int | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return str(value).strip()


class BudgetSubcategoryUpdate(BaseModel):
    group: BudgetGroup | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None


class BudgetSubcategoryOut(ORMModel):
    id: UUID
    family_id: UUID
    group: str
    name: str
    sort_order: int
    role: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BudgetSubcategoryGroupOut(BaseModel):
    group: str
    direction: str
    subcategories: list[BudgetSubcategoryOut]


class BudgetSubcategoryListOut(BaseModel):
    groups: list[BudgetSubcategoryGroupOut]


assert set(BUDGET_GROUPS) == {
    "Income",
    "Fixed Expense",
    "Variable Expense",
    "Debt",
    "Savings",
    "Investment",
}
