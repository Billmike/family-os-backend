from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member
from app.core.exceptions import bad_request
from app.core.timeutil import ensure_aware
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.event import EventCreate, EventOut, EventUpdate
from app.services import events as event_service

router = APIRouter(tags=["events"])

MAX_EVENT_WINDOW = timedelta(days=366)


@router.get("/api/families/{family_id}/events", response_model=list[EventOut])
def list_events(
    family_id: UUID,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    now = datetime.now(timezone.utc)
    window_start = ensure_aware(from_ or now - timedelta(days=1))
    window_end = ensure_aware(to or now + timedelta(days=14))
    if window_end <= window_start:
        raise bad_request("`to` must be after `from`")
    if window_end - window_start > MAX_EVENT_WINDOW:
        raise bad_request("Event window too large (max 366 days)")
    return event_service.list_events(db, family_id, window_start, window_end)


@router.post("/api/families/{family_id}/events", response_model=EventOut)
def create_event(
    family_id: UUID,
    data: EventCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> EventOut:
    event = event_service.create_event(db, family_id, user, data, background_tasks=background_tasks)
    return event_service.event_to_out(event)


@router.patch("/api/events/{event_id}", response_model=EventOut)
def patch_event(
    event_id: UUID,
    data: EventUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EventOut:
    event = event_service.get_family_event(db, event_id)
    get_membership(db, event.family_id, user.id)
    event = event_service.update_event(db, event, data)
    return event_service.event_to_out(event)


@router.delete("/api/events/{event_id}", status_code=204)
def delete_event(
    event_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    event = event_service.get_family_event(db, event_id)
    get_membership(db, event.family_id, user.id)
    event_service.delete_event(db, event)
