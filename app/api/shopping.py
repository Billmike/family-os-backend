from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.shopping import (
    ShoppingItemCreate,
    ShoppingItemOut,
    ShoppingItemUpdate,
    ShoppingListCreate,
    ShoppingListOut,
)
from app.services import shopping as shopping_service

router = APIRouter(tags=["shopping"])


@router.get("/api/families/{family_id}/shopping-lists", response_model=list[ShoppingListOut])
def get_lists(
    family_id: UUID,
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> list[ShoppingListOut]:
    return [shopping_service.list_to_out(lst) for lst in shopping_service.list_shopping_lists(db, family_id)]


@router.post("/api/families/{family_id}/shopping-lists", response_model=ShoppingListOut)
def create_list(
    family_id: UUID,
    data: ShoppingListCreate,
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> ShoppingListOut:
    lst = shopping_service.create_shopping_list(db, family_id, data)
    return shopping_service.list_to_out(lst)


@router.get("/api/shopping-lists/{list_id}/items", response_model=list[ShoppingItemOut])
def get_items(
    list_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ShoppingItemOut]:
    lst = shopping_service.get_list(db, list_id)
    get_membership(db, lst.family_id, user.id)
    return [shopping_service.item_to_out(i) for i in shopping_service.list_items(db, list_id)]


@router.post("/api/shopping-lists/{list_id}/items", response_model=ShoppingItemOut)
def create_item(
    list_id: UUID,
    data: ShoppingItemCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShoppingItemOut:
    lst = shopping_service.get_list(db, list_id)
    get_membership(db, lst.family_id, user.id)
    item = shopping_service.create_item(db, lst, user, data, background_tasks=background_tasks)
    return shopping_service.item_to_out(item)


@router.patch("/api/shopping-items/{item_id}", response_model=ShoppingItemOut)
def patch_item(
    item_id: UUID,
    data: ShoppingItemUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShoppingItemOut:
    item = shopping_service.get_item(db, item_id)
    get_membership(db, item.shopping_list.family_id, user.id)
    item = shopping_service.update_item(db, item, user, data, background_tasks=background_tasks)
    return shopping_service.item_to_out(item)


@router.delete("/api/shopping-items/{item_id}", status_code=204)
def delete_item(
    item_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    item = shopping_service.get_item(db, item_id)
    get_membership(db, item.shopping_list.family_id, user.id)
    shopping_service.delete_item(db, item)
