from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


AssistantDestination = Literal["household", "personal"]
TaskDue = Literal["today", "tomorrow"]
TaskPriority = Literal["low", "medium", "high"]


class AssistantMessageIn(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=500)


class AssistantTurnRequest(BaseModel):
    messages: list[AssistantMessageIn] = Field(min_length=1, max_length=20)
    destination_hint: AssistantDestination | None = None


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


class TaskProposal(BaseModel):
    title: str | None = None
    assignee_id: UUID | None = None
    due: TaskDue | None = None
    priority: TaskPriority | None = None
    category: str | None = None
    recurring: bool = False
    title_explicit: bool = False
    assignee_id_explicit: bool = False
    due_explicit: bool = False
    priority_explicit: bool = False
    category_explicit: bool = False
    recurring_explicit: bool = False


class ExpenseListRow(BaseModel):
    id: UUID
    occurred_on: date
    merchant: str | None = None
    amount: Decimal
    category_or_subcategory_label: str | None = None
    source_type: str
    writable: bool
    subcategory_id: UUID | None = None
    note: str | None = None


class ExpenseList(BaseModel):
    destination: AssistantDestination
    account_id: UUID | None = None
    account_name: str | None = None
    month: str | None = None
    period_id: UUID | None = None
    period_label: str | None = None
    count: int
    total: Decimal
    currency: str
    rows: list[ExpenseListRow]


class ExpenseChangeProposal(BaseModel):
    expense_id: UUID
    destination: AssistantDestination
    account_id: UUID | None = None
    amount: Decimal | None = None
    subcategory_id: UUID | None = None
    category: str | None = None
    merchant: str | None = None
    note: str | None = None
    occurred_on: date | None = None
    amount_explicit: bool = False
    subcategory_id_explicit: bool = False
    category_explicit: bool = False
    merchant_explicit: bool = False
    note_explicit: bool = False
    occurred_on_explicit: bool = False
    destination_explicit: bool = False
    account_id_explicit: bool = False
    writable: bool = True


class AssistantTurnOut(BaseModel):
    assistant_text: str
    proposal: ExpenseProposal | None = None
    task_proposal: TaskProposal | None = None
    expense_list: ExpenseList | None = None
    change_proposal: ExpenseChangeProposal | None = None

    @model_validator(mode="after")
    def at_most_one_structured_result(self) -> "AssistantTurnOut":
        results = [self.proposal, self.task_proposal, self.expense_list, self.change_proposal]
        if sum(item is not None for item in results) > 1:
            raise ValueError("at most one structured Assistant result")
        return self
