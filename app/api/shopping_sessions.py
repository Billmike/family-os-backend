from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member
from app.core.exceptions import not_found
from app.models.family import FamilyMember
from app.models.shopping_session import ShoppingSessionItem
from app.models.user import User
from app.schemas.shopping_session import (
    AddToBasketRequest,
    AddToBasketResponse,
    CompleteSessionRequest,
    RemoveFromBasketResponse,
    ShoppingSessionOut,
)
from app.services import shopping_session as session_service

router = APIRouter(tags=["shopping-sessions"])


@router.get(
    "/api/families/{family_id}/shopping-sessions/active",
    response_model=ShoppingSessionOut | None,
)
def get_active_session(
    family_id: UUID,
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> ShoppingSessionOut | None:
    session = session_service.get_active_session(db, family_id)
    if session is None:
        return None
    return session_service.get_session_out(db, session.id)


@router.post(
    "/api/families/{family_id}/shopping-sessions/active/items",
    response_model=AddToBasketResponse,
)
def add_to_basket(
    family_id: UUID,
    data: AddToBasketRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> AddToBasketResponse:
    return session_service.add_to_basket(
        db, family_id, user, data.item_id, background_tasks=background_tasks
    )


@router.delete(
    "/api/shopping-session-items/{session_item_id}",
    response_model=RemoveFromBasketResponse,
)
def remove_from_basket(
    session_item_id: UUID,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RemoveFromBasketResponse:
    session_item = db.get(ShoppingSessionItem, session_item_id)
    if session_item is None:
        raise not_found("Basket item not found")
    session = session_service.get_session(db, session_item.session_id)
    get_membership(db, session.family_id, user.id)
    return session_service.remove_from_basket(
        db, session_item_id, user, background_tasks=background_tasks
    )


@router.post(
    "/api/families/{family_id}/shopping-sessions/active/complete",
    response_model=ShoppingSessionOut,
)
def complete_session(
    family_id: UUID,
    data: CompleteSessionRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> ShoppingSessionOut:
    return session_service.complete_session(
        db, family_id, user, data, background_tasks=background_tasks
    )


@router.get(
    "/api/families/{family_id}/shopping-sessions",
    response_model=list[ShoppingSessionOut],
)
def list_sessions(
    family_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> list[ShoppingSessionOut]:
    return session_service.list_completed_sessions(db, family_id, limit=limit, offset=offset)


@router.get("/api/shopping-sessions/{session_id}", response_model=ShoppingSessionOut)
def get_session_detail(
    session_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShoppingSessionOut:
    session = session_service.get_session(db, session_id)
    get_membership(db, session.family_id, user.id)
    return session_service.get_session_out(db, session_id)
