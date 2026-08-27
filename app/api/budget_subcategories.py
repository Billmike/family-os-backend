from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member, require_parent_or_owner
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.budget_subcategory import (
    BudgetSubcategoryCreate,
    BudgetSubcategoryListOut,
    BudgetSubcategoryOut,
    BudgetSubcategoryUpdate,
)
from app.services import budget_subcategory as subcategory_service
from app.services import family as family_service

router = APIRouter(tags=["budget-subcategories"])


@router.get(
    "/api/families/{family_id}/budget-subcategories",
    response_model=BudgetSubcategoryListOut,
)
def list_budget_subcategories(
    family_id: UUID,
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> BudgetSubcategoryListOut:
    family = family_service.get_family(db, family_id)
    return subcategory_service.list_subcategories(db, family)


@router.post(
    "/api/families/{family_id}/budget-subcategories",
    response_model=BudgetSubcategoryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_budget_subcategory(
    family_id: UUID,
    data: BudgetSubcategoryCreate,
    _: FamilyMember = Depends(require_parent_or_owner),
    db: Session = Depends(get_db),
) -> BudgetSubcategoryOut:
    family = family_service.get_family(db, family_id)
    return subcategory_service.create_subcategory(db, family, data)


@router.patch("/api/budget-subcategories/{subcategory_id}", response_model=BudgetSubcategoryOut)
def patch_budget_subcategory(
    subcategory_id: UUID,
    data: BudgetSubcategoryUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BudgetSubcategoryOut:
    row = subcategory_service.get_subcategory(db, subcategory_id)
    member = get_membership(db, row.family_id, user.id)
    require_parent_or_owner(member)
    family = family_service.get_family(db, row.family_id)
    return subcategory_service.update_subcategory(db, family, row, data)


@router.delete("/api/budget-subcategories/{subcategory_id}", status_code=204)
def delete_budget_subcategory(
    subcategory_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    row = subcategory_service.get_subcategory(db, subcategory_id)
    member = get_membership(db, row.family_id, user.id)
    require_parent_or_owner(member)
    family = family_service.get_family(db, row.family_id)
    subcategory_service.archive_subcategory(db, family, row)
