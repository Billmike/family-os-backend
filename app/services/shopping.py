from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import not_found
from app.models.shopping import ShoppingItem, ShoppingList
from app.models.user import User
from app.realtime.hub import hub
from app.schemas.shopping import ShoppingItemCreate, ShoppingItemOut, ShoppingItemUpdate, ShoppingListCreate, ShoppingListOut


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


def create_item(db: Session, lst: ShoppingList, user: User, data: ShoppingItemCreate) -> ShoppingItem:
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
    return item


def get_item(db: Session, item_id: UUID) -> ShoppingItem:
    item = db.get(ShoppingItem, item_id)
    if item is None:
        raise not_found("Shopping item not found")
    return item


def update_item(db: Session, item: ShoppingItem, user: User, data: ShoppingItemUpdate) -> ShoppingItem:
    if data.name is not None:
        item.name = data.name.strip()
    if data.quantity is not None:
        item.quantity = data.quantity
    if data.unit is not None:
        item.unit = data.unit
    if data.category is not None:
        item.category = data.category
    event_type = "shopping.item.updated"
    if data.completed is not None:
        if data.completed and item.completed_at is None:
            item.completed_at = datetime.now(timezone.utc)
            item.completed_by = user.id
            event_type = "shopping.item.completed"
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
    return item


def delete_item(db: Session, item: ShoppingItem) -> None:
    family_id = item.shopping_list.family_id
    item_id = item.id
    db.delete(item)
    db.commit()
    hub.broadcast(family_id, {"type": "shopping.item.updated", "item_id": str(item_id), "deleted": True})
