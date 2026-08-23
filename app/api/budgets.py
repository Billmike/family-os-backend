from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member, require_parent_or_owner
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.budget import (
    BudgetOut,
    BudgetPeriodCreate,
    BudgetPeriodListOut,
    BudgetPeriodOut,
    BudgetPeriodUpdate,
    BudgetUpdate,
)
from app.services import budget as budget_service
from app.services import family as family_service

router = APIRouter(tags=["budgets"])


@router.get(
    "/api/families/{family_id}/budget-periods/current",
    response_model=BudgetPeriodOut | None,
)
def get_current_budget_period(
    family_id: UUID,
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> BudgetPeriodOut | None:
    family = family_service.get_family(db, family_id)
    return budget_service.get_current_period_out(db, family)


@router.get("/api/families/{family_id}/budget-periods", response_model=BudgetPeriodListOut)
def list_budget_periods(
    family_id: UUID,
    include: str = Query(default="current,past", description="Comma list: current,past,upcoming"),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> BudgetPeriodListOut:
    family = family_service.get_family(db, family_id)
    return budget_service.list_periods(db, family, include=include)


@router.post(
    "/api/families/{family_id}/budget-periods",
    response_model=BudgetPeriodOut,
    status_code=status.HTTP_201_CREATED,
)
def create_budget_period(
    family_id: UUID,
    data: BudgetPeriodCreate,
    user: User = Depends(get_current_user),
    _: FamilyMember = Depends(require_parent_or_owner),
    db: Session = Depends(get_db),
) -> BudgetPeriodOut:
    family = family_service.get_family(db, family_id)
    return budget_service.create_period(db, family, user, data)


@router.patch("/api/budget-periods/{period_id}", response_model=BudgetPeriodOut)
def patch_budget_period(
    period_id: UUID,
    data: BudgetPeriodUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BudgetPeriodOut:
    period = budget_service.get_period(db, period_id)
    member = get_membership(db, period.family_id, user.id)
    require_parent_or_owner(member)
    family = family_service.get_family(db, period.family_id)
    return budget_service.update_period(db, family, period, data)


@router.delete("/api/budget-periods/{period_id}", status_code=204)
def delete_budget_period(
    period_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    period = budget_service.get_period(db, period_id)
    member = get_membership(db, period.family_id, user.id)
    require_parent_or_owner(member)
    budget_service.delete_period(db, period)


@router.patch("/api/budgets/{budget_id}", response_model=BudgetOut)
def patch_budget(
    budget_id: UUID,
    data: BudgetUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BudgetOut:
    budget = budget_service.get_budget(db, budget_id)
    period = budget_service.get_period(db, budget.period_id)
    member = get_membership(db, period.family_id, user.id)
    require_parent_or_owner(member)
    family = family_service.get_family(db, period.family_id)
    return budget_service.update_budget(db, family, budget, data)


@router.delete("/api/budgets/{budget_id}", status_code=204)
def delete_budget(
    budget_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    budget = budget_service.get_budget(db, budget_id)
    period = budget_service.get_period(db, budget.period_id)
    member = get_membership(db, period.family_id, user.id)
    require_parent_or_owner(member)
    budget_service.delete_budget(db, budget)
