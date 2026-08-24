from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.auth import ORMModel
from app.schemas.shopping import MAX_SHOPPING_CATEGORY, MAX_SHOPPING_UNIT


class ShoppingSessionItemOut(ORMModel):
    id: UUID
    session_id: UUID
    name: str
    quantity: Decimal | None
    unit: str | None
    category: str | None
    location_id: UUID | None
    location_name: str | None
    added_at: datetime
    added_by: UUID


class ShoppingSessionOut(ORMModel):
    id: UUID
    family_id: UUID
    status: str
    started_at: datetime
    started_by: UUID
    completed_at: datetime | None
    completed_by: UUID | None
    total_cost: Decimal | None
    currency: str
    created_at: datetime
    updated_at: datetime
    item_count: int = 0
    items: list[ShoppingSessionItemOut] = Field(default_factory=list)


class AddToBasketRequest(BaseModel):
    item_id: UUID


class CompleteSessionRequest(BaseModel):
    total_cost: Decimal = Field(gt=0)


class MonthlySpendOut(BaseModel):
    month: str
    total: Decimal
    trip_count: int
    average: Decimal


class ShoppingSpendOut(BaseModel):
    currency: str
    current_month: str
    year_to_date_total: Decimal
    months: list[MonthlySpendOut]


class UpdateSessionItemRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=MAX_SHOPPING_UNIT)
    category: str | None = Field(default=None, max_length=MAX_SHOPPING_CATEGORY)
    location_id: UUID | None = None


class AddToBasketResponse(BaseModel):
    session: ShoppingSessionOut
    item: ShoppingSessionItemOut


class RemoveFromBasketResponse(BaseModel):
    session_id: UUID
    item_id: UUID
    restored_item: "ShoppingItemOut | None" = None


from app.schemas.shopping import ShoppingItemOut  # noqa: E402

RemoveFromBasketResponse.model_rebuild()
