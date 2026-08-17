from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import bad_request, conflict, not_found
from app.models.shopping import ShoppingItem, ShoppingList, ShoppingLocation
from app.models.shopping_session import (
    SESSION_STATUS_ACTIVE,
    SESSION_STATUS_COMPLETED,
    ShoppingSession,
    ShoppingSessionItem,
)
from app.models.user import User
from app.realtime.hub import hub
from app.schemas.shopping import ShoppingItemOut, ShoppingListCreate
from app.schemas.shopping_session import (
    AddToBasketResponse,
    CompleteSessionRequest,
    RemoveFromBasketResponse,
    ShoppingSessionItemOut,
    ShoppingSessionOut,
)
from app.services import notifications as notification_service
from app.services import shopping as shopping_service


def _session_item_to_out(item: ShoppingSessionItem) -> ShoppingSessionItemOut:
    return ShoppingSessionItemOut.model_validate(item)


def _session_to_out(session: ShoppingSession, *, include_items: bool = True) -> ShoppingSessionOut:
    items = list(session.items) if include_items else []
    item_count = len(session.items) if session.items is not None else 0
    return ShoppingSessionOut(
        id=session.id,
        family_id=session.family_id,
        status=session.status,
        started_at=session.started_at,
        started_by=session.started_by,
        completed_at=session.completed_at,
        completed_by=session.completed_by,
        total_cost=session.total_cost,
        currency=session.currency,
        created_at=session.created_at,
        updated_at=session.updated_at,
        item_count=item_count if include_items else item_count,
        items=[_session_item_to_out(i) for i in items] if include_items else [],
    )


def _load_active_session(db: Session, family_id: UUID) -> ShoppingSession | None:
    return (
        db.query(ShoppingSession)
        .options(joinedload(ShoppingSession.items))
        .filter(
            ShoppingSession.family_id == family_id,
            ShoppingSession.status == SESSION_STATUS_ACTIVE,
        )
        .first()
    )


def _get_or_create_active_session(db: Session, family_id: UUID, user: User) -> ShoppingSession:
    session = _load_active_session(db, family_id)
    if session is not None:
        return session

    now = datetime.now(timezone.utc)
    session = ShoppingSession(
        family_id=family_id,
        status=SESSION_STATUS_ACTIVE,
        started_at=now,
        started_by=user.id,
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        session = _load_active_session(db, family_id)
        if session is None:
            raise
        return session
    db.refresh(session)
    hub.broadcast(
        family_id,
        {
            "type": "shopping.session.started",
            "session": _session_to_out(session, include_items=False).model_dump(mode="json"),
        },
    )
    return session


def _resolve_groceries_list(db: Session, family_id: UUID) -> ShoppingList:
    lists = shopping_service.list_shopping_lists(db, family_id)
    groceries = next((lst for lst in lists if lst.name.lower() == "groceries"), None)
    if groceries is not None:
        return groceries
    if lists:
        return lists[0]
    return shopping_service.create_shopping_list(db, family_id, ShoppingListCreate(name="Groceries"))


def get_active_session(db: Session, family_id: UUID) -> ShoppingSession | None:
    return _load_active_session(db, family_id)


def add_to_basket(
    db: Session,
    family_id: UUID,
    user: User,
    item_id: UUID,
    background_tasks: BackgroundTasks | None = None,
) -> AddToBasketResponse:
    item = shopping_service.get_item(db, item_id)
    if item.shopping_list.family_id != family_id:
        raise not_found("Shopping item not found")

    location_name: str | None = None
    if item.location_id is not None:
        loc = db.get(ShoppingLocation, item.location_id)
        location_name = loc.name if loc else None

    session = _get_or_create_active_session(db, family_id, user)
    now = datetime.now(timezone.utc)
    session_item = ShoppingSessionItem(
        session_id=session.id,
        name=item.name,
        quantity=item.quantity,
        unit=item.unit,
        category=item.category,
        location_id=item.location_id,
        location_name=location_name,
        added_at=now,
        added_by=user.id,
    )
    db.add(session_item)
    db.delete(item)
    session.updated_at = now
    db.commit()
    db.refresh(session_item)
    session = _load_active_session(db, family_id)
    if session is None:
        raise not_found("Active shopping session not found")

    session_out = _session_to_out(session)
    item_out = _session_item_to_out(session_item)
    hub.broadcast(
        family_id,
        {
            "type": "shopping.session.item.added",
            "session": session_out.model_dump(mode="json"),
            "item": item_out.model_dump(mode="json"),
            "removed_item_id": str(item_id),
        },
    )
    hub.broadcast(
        family_id,
        {"type": "shopping.item.updated", "item_id": str(item_id), "deleted": True},
    )
    notification_service.notify_family_members(
        db,
        family_id=family_id,
        actor_user_id=user.id,
        pref_field="shopping_activity",
        type="shopping",
        title="Shopping list",
        body=f"{session_item.name} added to basket",
        entity_type="shopping_session",
        entity_id=session.id,
        background_tasks=background_tasks,
    )
    return AddToBasketResponse(session=session_out, item=item_out)


def remove_from_basket(
    db: Session,
    session_item_id: UUID,
    user: User,
    background_tasks: BackgroundTasks | None = None,
) -> RemoveFromBasketResponse:
    session_item = db.get(ShoppingSessionItem, session_item_id)
    if session_item is None:
        raise not_found("Basket item not found")

    session = db.get(ShoppingSession, session_item.session_id)
    if session is None:
        raise not_found("Shopping session not found")
    if session.status != SESSION_STATUS_ACTIVE:
        raise conflict("Shopping session is no longer active")

    lst = _resolve_groceries_list(db, session.family_id)
    restored = ShoppingItem(
        shopping_list_id=lst.id,
        name=session_item.name,
        quantity=session_item.quantity,
        unit=session_item.unit,
        category=session_item.category,
        location_id=session_item.location_id,
        created_by=user.id,
    )
    db.add(restored)
    session_item_id_str = str(session_item.id)
    session_id = session.id
    family_id = session.family_id
    db.delete(session_item)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(restored)

    restored_out = shopping_service.item_to_out(restored)
    hub.broadcast(
        family_id,
        {
            "type": "shopping.session.item.removed",
            "session_id": str(session_id),
            "item_id": session_item_id_str,
            "restored_item": restored_out.model_dump(mode="json"),
        },
    )
    hub.broadcast(
        family_id,
        {"type": "shopping.item.created", "item": restored_out.model_dump(mode="json")},
    )
    return RemoveFromBasketResponse(
        session_id=session_id,
        item_id=UUID(session_item_id_str),
        restored_item=restored_out,
    )


def complete_session(
    db: Session,
    family_id: UUID,
    user: User,
    data: CompleteSessionRequest,
    background_tasks: BackgroundTasks | None = None,
) -> ShoppingSessionOut:
    session = _load_active_session(db, family_id)
    if session is None:
        raise not_found("No active shopping session")
    if not session.items:
        raise bad_request("Add at least one item before completing")

    now = datetime.now(timezone.utc)
    session.status = SESSION_STATUS_COMPLETED
    session.completed_at = now
    session.completed_by = user.id
    session.total_cost = data.total_cost
    session.updated_at = now
    db.commit()
    db.refresh(session)

    session_out = _session_to_out(session)
    cost_label = f"€{data.total_cost:.2f}"
    hub.broadcast(
        family_id,
        {
            "type": "shopping.session.completed",
            "session": session_out.model_dump(mode="json"),
        },
    )
    notification_service.notify_family_members(
        db,
        family_id=family_id,
        actor_user_id=user.id,
        pref_field="shopping_activity",
        type="shopping",
        title="Shopping trip completed",
        body=f"Shopping trip completed — {cost_label}",
        entity_type="shopping_session",
        entity_id=session.id,
        background_tasks=background_tasks,
    )
    return session_out


def list_completed_sessions(
    db: Session, family_id: UUID, *, limit: int = 20, offset: int = 0
) -> list[ShoppingSessionOut]:
    sessions = (
        db.query(ShoppingSession)
        .options(joinedload(ShoppingSession.items))
        .filter(
            ShoppingSession.family_id == family_id,
            ShoppingSession.status == SESSION_STATUS_COMPLETED,
        )
        .order_by(ShoppingSession.completed_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_session_to_out(s, include_items=False) for s in sessions]


def get_session(db: Session, session_id: UUID) -> ShoppingSession:
    session = (
        db.query(ShoppingSession)
        .options(joinedload(ShoppingSession.items))
        .filter(ShoppingSession.id == session_id)
        .first()
    )
    if session is None:
        raise not_found("Shopping session not found")
    return session


def get_session_out(db: Session, session_id: UUID) -> ShoppingSessionOut:
    return _session_to_out(get_session(db, session_id))
