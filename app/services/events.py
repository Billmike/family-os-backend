from datetime import datetime, timezone
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, not_found
from app.core.timeutil import ensure_aware, expand_occurrences
from app.models.event import Event, EventMember, EventReminder
from app.models.family import FamilyMember
from app.models.user import User
from app.realtime.hub import hub
from app.schemas.event import EventCreate, EventOut, EventUpdate
from app.services import notifications as notification_service


def _broadcast_event(event: Event, type_: str) -> None:
    hub.broadcast(
        event.family_id,
        {"type": type_, "event": event_to_out(event).model_dump(mode="json")},
    )


def event_to_out(event: Event, occurrence_starts_at: datetime | None = None) -> EventOut:
    return EventOut(
        id=event.id,
        family_id=event.family_id,
        title=event.title,
        description=event.description,
        location=event.location,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        all_day=event.all_day,
        recurrence_rule=event.recurrence_rule,
        created_by=event.created_by,
        member_ids=[m.family_member_id for m in event.members],
        reminder_minutes=[r.minutes_before for r in event.reminders],
        created_at=event.created_at,
        updated_at=event.updated_at,
        occurrence_starts_at=occurrence_starts_at,
    )


def _validate_members(db: Session, family_id: UUID, member_ids: list[UUID]) -> None:
    if not member_ids:
        return
    count = (
        db.query(FamilyMember)
        .filter(FamilyMember.family_id == family_id, FamilyMember.id.in_(member_ids))
        .count()
    )
    if count != len(set(member_ids)):
        raise bad_request("One or more members are not in this family")


def create_event(
    db: Session,
    family_id: UUID,
    user: User,
    data: EventCreate,
    background_tasks: BackgroundTasks | None = None,
) -> Event:
    _validate_members(db, family_id, data.member_ids)
    event = Event(
        family_id=family_id,
        title=data.title.strip(),
        description=data.description,
        location=data.location,
        starts_at=ensure_aware(data.starts_at),
        ends_at=ensure_aware(data.ends_at) if data.ends_at else None,
        all_day=data.all_day,
        recurrence_rule=data.recurrence_rule,
        created_by=user.id,
    )
    db.add(event)
    db.flush()
    for mid in data.member_ids:
        db.add(EventMember(event_id=event.id, family_member_id=mid))
    for minutes in data.reminder_minutes:
        db.add(EventReminder(event_id=event.id, minutes_before=minutes))
    db.commit()
    db.refresh(event)
    _broadcast_event(event, "event.created")
    notification_service.notify_family_members(
        db,
        family_id=family_id,
        actor_user_id=user.id,
        pref_field="calendar_reminders",
        type="calendar",
        title="New event",
        body=event.title,
        entity_type="event",
        entity_id=event.id,
        background_tasks=background_tasks,
    )
    return event


def get_family_event(db: Session, event_id: UUID, family_id: UUID | None = None) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise not_found("Event not found")
    if family_id is not None and event.family_id != family_id:
        raise not_found("Event not found")
    return event


def list_events(
    db: Session,
    family_id: UUID,
    window_start: datetime,
    window_end: datetime,
) -> list[EventOut]:
    ws = ensure_aware(window_start)
    we = ensure_aware(window_end)
    # Fetch events that could overlap the window (including recurring that started earlier)
    events = (
        db.query(Event)
        .filter(Event.family_id == family_id, Event.starts_at < we)
        .order_by(Event.starts_at.asc())
        .all()
    )
    results: list[EventOut] = []
    for event in events:
        if event.recurrence_rule:
            for occ in expand_occurrences(event.starts_at, event.recurrence_rule, ws, we):
                results.append(event_to_out(event, occurrence_starts_at=occ))
        else:
            start = ensure_aware(event.starts_at)
            end = ensure_aware(event.ends_at) if event.ends_at else start
            if start < we and end >= ws:
                results.append(event_to_out(event))
    results.sort(key=lambda e: e.occurrence_starts_at or e.starts_at)
    return results


def update_event(db: Session, event: Event, data: EventUpdate) -> Event:
    if data.title is not None:
        event.title = data.title.strip()
    if data.description is not None:
        event.description = data.description
    if data.location is not None:
        event.location = data.location
    if data.starts_at is not None:
        event.starts_at = ensure_aware(data.starts_at)
    if data.ends_at is not None:
        event.ends_at = ensure_aware(data.ends_at)
    if data.all_day is not None:
        event.all_day = data.all_day
    if data.recurrence_rule is not None:
        event.recurrence_rule = data.recurrence_rule
    if data.member_ids is not None:
        _validate_members(db, event.family_id, data.member_ids)
        event.members.clear()
        db.flush()
        for mid in data.member_ids:
            db.add(EventMember(event_id=event.id, family_member_id=mid))
    if data.reminder_minutes is not None:
        event.reminders.clear()
        db.flush()
        for minutes in data.reminder_minutes:
            db.add(EventReminder(event_id=event.id, minutes_before=minutes))
    event.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(event)
    _broadcast_event(event, "event.updated")
    return event


def delete_event(db: Session, event: Event) -> None:
    family_id = event.family_id
    event_id = event.id
    db.delete(event)
    db.commit()
    hub.broadcast(family_id, {"type": "event.deleted", "event_id": str(event_id)})
