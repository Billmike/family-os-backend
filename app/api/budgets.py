from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member, require_parent_or_owner
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.budget import BudgetCreate, BudgetListOut, BudgetOut, BudgetUpdate
from app.services import budget as budget_service
from app.services import family as family_service

router = APIRouter(tags=["budgets"])


@router.get("/api/families/{family_id}/budgets", response_model=BudgetListOut)
def list_budgets(
    family_id: UUID,
    month: str | None = Query(default=None, description="YYYY-MM in the family timezone"),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> BudgetListOut:
    family = family_service.get_family(db, family_id)
    return budget_service.list_budgets(db, family, month=month)


@router.post(
    "/api/families/{family_id}/budgets",
    response_model=BudgetOut,
    status_code=status.HTTP_201_CREATED,
)
def create_budget(
    family_id: UUID,
    data: BudgetCreate,
    response: Response,
    user: User = Depends(get_current_user),
    _: FamilyMember = Depends(require_parent_or_owner),
    db: Session = Depends(get_db),
) -> BudgetOut:
    family = family_service.get_family(db, family_id)
    out, created = budget_service.upsert_budget(db, family, user, data)
    if not created:
        response.status_code = status.HTTP_200_OK
    return out


@router.patch("/api/budgets/{budget_id}", response_model=BudgetOut)
def patch_budget(
    budget_id: UUID,
    data: BudgetUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BudgetOut:
    budget = budget_service.get_budget(db, budget_id)
    member = get_membership(db, budget.family_id, user.id)
    require_parent_or_owner(member)
    family = family_service.get_family(db, budget.family_id)
    return budget_service.update_budget(db, family, budget, data)


@router.delete("/api/budgets/{budget_id}", status_code=204)
def delete_budget(
    budget_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    budget = budget_service.get_budget(db, budget_id)
    member = get_membership(db, budget.family_id, user.id)
    require_parent_or_owner(member)
    budget_service.delete_budget(db, budget)
