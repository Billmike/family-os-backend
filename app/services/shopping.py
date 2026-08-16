from datetime import datetime, timezone
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, conflict, not_found
from app.models.shopping import ShoppingItem, ShoppingList, ShoppingLocation
from app.models.user import User
from app.realtime.hub import hub
from app.schemas.shopping import (
    ShoppingItemCreate,
    ShoppingItemOut,
    ShoppingItemUpdate,
    ShoppingListCreate,
    ShoppingListOut,
    ShoppingLocationCreate,
    ShoppingLocationOut,
    ShoppingLocationUpdate,
)
from app.services import notifications as notification_service


def list_to_out(lst: ShoppingList) -> ShoppingListOut:
    return ShoppingListOut.model_validate(lst)


def location_to_out(loc: ShoppingLocation) -> ShoppingLocationOut:
    return ShoppingLocationOut.model_validate(loc)


def item_to_out(item: ShoppingItem) -> ShoppingItemOut:
    return ShoppingItemOut.model_validate(item)


def list_shopping_lists(db: Session, family_id: UUID) -> list[ShoppingList]:
    return (
        db.query(ShoppingList)
        .filter(ShoppingList.family_id == family_id)
        .order_by(ShoppingList.created_at.asc())
        .all()
    )


def create_shopping_list(db: Session, family_id: UUID, data: ShoppingListCreate) -> ShoppingList:
    lst = ShoppingList(family_id=family_id, name=data.name.strip())
    db.add(lst)
    db.commit()
    db.refresh(lst)
    return lst


def get_list(db: Session, list_id: UUID) -> ShoppingList:
    lst = db.get(ShoppingList, list_id)
    if lst is None:
        raise not_found("Shopping list not found")
    return lst


def list_locations(db: Session, family_id: UUID) -> list[ShoppingLocation]:
    return (
        db.query(ShoppingLocation)
        .filter(ShoppingLocation.family_id == family_id)
        .order_by(ShoppingLocation.sort_order.asc(), ShoppingLocation.name.asc())
        .all()
    )


def create_location(db: Session, family_id: UUID, data: ShoppingLocationCreate) -> ShoppingLocation:
    name = data.name.strip()
    max_order = (
        db.query(ShoppingLocation.sort_order)
        .filter(ShoppingLocation.family_id == family_id)
        .order_by(ShoppingLocation.sort_order.desc())
        .first()
    )
    next_order = (max_order[0] + 1) if max_order else 0
    loc = ShoppingLocation(family_id=family_id, name=name, sort_order=next_order)
    db.add(loc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("Shopping location already exists")
    db.refresh(loc)
    return loc


def get_location(db: Session, location_id: UUID) -> ShoppingLocation:
    loc = db.get(ShoppingLocation, location_id)
    if loc is None:
        raise not_found("Shopping location not found")
    return loc


def update_location(db: Session, loc: ShoppingLocation, data: ShoppingLocationUpdate) -> ShoppingLocation:
    if data.name is not None:
        loc.name = data.name.strip()
    if data.sort_order is not None:
        loc.sort_order = data.sort_order
    loc.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("Shopping location already exists")
    db.refresh(loc)
    return loc


def delete_location(db: Session, loc: ShoppingLocation) -> None:
    db.delete(loc)
    db.commit()


def _resolve_location_for_family(
    db: Session, family_id: UUID, location_id: UUID | None
) -> UUID | None:
    if location_id is None:
        return None
    loc = db.get(ShoppingLocation, location_id)
    if loc is None or loc.family_id != family_id:
        raise bad_request("Shopping location does not belong to this family")
    return loc.id


def list_items(db: Session, list_id: UUID) -> list[ShoppingItem]:
    return (
        db.query(ShoppingItem)
        .filter(ShoppingItem.shopping_list_id == list_id)
        .order_by(ShoppingItem.completed_at.asc().nullsfirst(), ShoppingItem.created_at.desc())
        .all()
    )


def create_item(
    db: Session,
    lst: ShoppingList,
    user: User,
    data: ShoppingItemCreate,
    background_tasks: BackgroundTasks | None = None,
) -> ShoppingItem:
    location_id = _resolve_location_for_family(db, lst.family_id, data.location_id)
    item = ShoppingItem(
        shopping_list_id=lst.id,
        name=data.name.strip(),
        quantity=data.quantity,
        unit=data.unit,
        category=data.category,
        location_id=location_id,
        created_by=user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    hub.broadcast(
        lst.family_id,
        {"type": "shopping.item.created", "item": item_to_out(item).model_dump(mode="json")},
    )
    notification_service.notify_family_members(
        db,
        family_id=lst.family_id,
        actor_user_id=user.id,
        pref_field="shopping_activity",
        type="shopping",
        title="Shopping list",
        body=f"{item.name} added",
        entity_type="shopping_item",
        entity_id=item.id,
        background_tasks=background_tasks,
    )
    return item


def get_item(db: Session, item_id: UUID) -> ShoppingItem:
    item = db.get(ShoppingItem, item_id)
    if item is None:
        raise not_found("Shopping item not found")
    return item


def update_item(
    db: Session,
    item: ShoppingItem,
    user: User,
    data: ShoppingItemUpdate,
    background_tasks: BackgroundTasks | None = None,
) -> ShoppingItem:
    if data.name is not None:
        item.name = data.name.strip()
    if data.quantity is not None:
        item.quantity = data.quantity
    if data.unit is not None:
        item.unit = data.unit
    if data.category is not None:
        item.category = data.category
    fields_set = data.model_dump(exclude_unset=True)
    if "location_id" in fields_set:
        item.location_id = _resolve_location_for_family(
            db, item.shopping_list.family_id, data.location_id
        )
    event_type = "shopping.item.updated"
    marked_bought = False
    if data.completed is not None:
        if data.completed and item.completed_at is None:
            item.completed_at = datetime.now(timezone.utc)
            item.completed_by = user.id
            event_type = "shopping.item.completed"
            marked_bought = True
        elif not data.completed:
            item.completed_at = None
            item.completed_by = None
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(item)
    family_id = item.shopping_list.family_id
    hub.broadcast(
        family_id,
        {"type": event_type, "item": item_to_out(item).model_dump(mode="json")},
    )
    if marked_bought:
        notification_service.notify_family_members(
            db,
            family_id=family_id,
            actor_user_id=user.id,
            pref_field="shopping_activity",
            type="shopping",
            title="Shopping list",
            body=f"{item.name} bought",
            entity_type="shopping_item",
            entity_id=item.id,
            background_tasks=background_tasks,
        )
    return item


def delete_item(db: Session, item: ShoppingItem) -> None:
    family_id = item.shopping_list.family_id
    item_id = item.id
    db.delete(item)
    db.commit()
    hub.broadcast(family_id, {"type": "shopping.item.updated", "item_id": str(item_id), "deleted": True})
