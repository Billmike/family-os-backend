from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.auth import ORMModel

MAX_TASK_DESCRIPTION = 2000


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_TASK_DESCRIPTION)
    due_at: datetime | None = None
    priority: str = Field(default="normal")
    category: str | None = None
    recurrence_rule: str | None = None
    assignee_ids: list[UUID] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=MAX_TASK_DESCRIPTION)
    due_at: datetime | None = None
    priority: str | None = None
    category: str | None = None
    recurrence_rule: str | None = None
    assignee_ids: list[UUID] | None = None
    completed_at: datetime | None = None


class TaskOut(ORMModel):
    id: UUID
    family_id: UUID
    title: str
    description: str | None
    due_at: datetime | None
    priority: str
    category: str | None
    recurrence_rule: str | None
    completed_at: datetime | None
    created_by: UUID
    assignee_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
