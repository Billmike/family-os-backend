from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.auth import ORMModel


class ShoppingListCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ShoppingListOut(ORMModel):
    id: UUID
    family_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class ShoppingItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: Decimal | None = None
    unit: str | None = None
    category: str | None = None


class ShoppingItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: Decimal | None = None
    unit: str | None = None
    category: str | None = None
    completed: bool | None = None


class ShoppingItemOut(ORMModel):
    id: UUID
    shopping_list_id: UUID
    name: str
    quantity: Decimal | None
    unit: str | None
    category: str | None
    completed_at: datetime | None
    created_by: UUID
    completed_by: UUID | None
    created_at: datetime
    updated_at: datetime
