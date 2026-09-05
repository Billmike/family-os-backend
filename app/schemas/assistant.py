from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class AssistantMessageIn(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=500)


class AssistantTurnRequest(BaseModel):
    messages: list[AssistantMessageIn] = Field(min_length=1, max_length=20)


class ExpenseProposal(BaseModel):
    destination: str | None = None
    account_id: UUID | None = None
    amount: Decimal | None = None
    subcategory_id: UUID | None = None
    category: str | None = None
    merchant: str | None = None
    note: str | None = None
    occurred_on: date | None = None
    destination_explicit: bool = False
    account_id_explicit: bool = False
    amount_explicit: bool = False
    subcategory_id_explicit: bool = False
    category_explicit: bool = False
    merchant_explicit: bool = False
    note_explicit: bool = False
    occurred_on_explicit: bool = False


class AssistantTurnOut(BaseModel):
    assistant_text: str
    proposal: ExpenseProposal | None = None
