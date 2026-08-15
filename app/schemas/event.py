from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.auth import ORMModel

MAX_REMINDER_MINUTES = 10080  # 7 days
MAX_REMINDERS_PER_EVENT = 10

ReminderMinute = Annotated[int, Field(ge=0, le=MAX_REMINDER_MINUTES)]


def _dedupe_reminder_minutes(values: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for minutes in values:
        if minutes not in seen:
            seen.add(minutes)
            out.append(minutes)
    return out


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    location: str | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    recurrence_rule: str | None = None
    member_ids: list[UUID] = Field(default_factory=list)
    reminder_minutes: list[ReminderMinute] = Field(
        default_factory=list, max_length=MAX_REMINDERS_PER_EVENT
    )

    @field_validator("reminder_minutes")
    @classmethod
    def dedupe_reminder_minutes(cls, value: list[int]) -> list[int]:
        return _dedupe_reminder_minutes(value)


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    location: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool | None = None
    recurrence_rule: str | None = None
    member_ids: list[UUID] | None = None
    reminder_minutes: list[ReminderMinute] | None = Field(
        default=None, max_length=MAX_REMINDERS_PER_EVENT
    )

    @field_validator("reminder_minutes")
    @classmethod
    def dedupe_reminder_minutes(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        return _dedupe_reminder_minutes(value)


class EventOut(ORMModel):
    id: UUID
    family_id: UUID
    title: str
    description: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool
    recurrence_rule: str | None
    created_by: UUID
    member_ids: list[UUID] = Field(default_factory=list)
    reminder_minutes: list[int] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    # For expanded recurring instances
    occurrence_starts_at: datetime | None = None
