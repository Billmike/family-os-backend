from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.auth import ORMModel
from app.schemas.event import EventOut
from app.schemas.shopping import ShoppingItemOut
from app.schemas.task import TaskOut


class DashboardOut(BaseModel):
    family_id: UUID
    family_name: str
    timezone: str
    member_name: str
    date: str
    today_events: list[EventOut]
    open_tasks: list[TaskOut]
    shopping_preview: list[ShoppingItemOut]
    upcoming_events: list[EventOut]


class NotificationOut(ORMModel):
    id: UUID
    family_id: UUID
    user_id: UUID
    type: str
    title: str
    body: str
    entity_type: str | None
    entity_id: UUID | None
    read_at: datetime | None
    created_at: datetime


class NotificationPreferencesOut(ORMModel):
    user_id: UUID
    calendar_reminders: bool
    task_assignments: bool
    task_due_soon: bool
    shopping_activity: bool
    family_activity: bool
    quiet_hours_start: str | None
    quiet_hours_end: str | None


class NotificationPreferencesUpdate(BaseModel):
    calendar_reminders: bool | None = None
    task_assignments: bool | None = None
    task_due_soon: bool | None = None
    shopping_activity: bool | None = None
    family_activity: bool | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None


class PushSubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    user_agent: str | None = None


class PushSubscriptionOut(ORMModel):
    id: UUID
    endpoint: str
    user_agent: str | None
    created_at: datetime
    last_used_at: datetime | None


class VapidPublicKeyOut(BaseModel):
    public_key: str | None
