from datetime import datetime, timezone
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.exceptions import not_found
from app.models.shopping import ShoppingItem, ShoppingList
from app.models.user import User
from app.realtime.hub import hub
from app.schemas.shopping import ShoppingItemCreate, ShoppingItemOut, ShoppingItemUpdate, ShoppingListCreate, ShoppingListOut
from app.services import notifications as notification_service


def list_to_out(lst: ShoppingList) -> ShoppingListOut:
    return ShoppingListOut.model_validate(lst)


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
    item = ShoppingItem(
        shopping_list_id=lst.id,
        name=data.name.strip(),
        quantity=data.quantity,
        unit=data.unit,
        category=data.category,
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
