from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.expense import ExpenseCreate, ExpenseOut, ExpenseUpdate, HouseholdSpendOut
from app.services import expense as expense_service
from app.services import family as family_service

router = APIRouter(tags=["expenses"])


@router.post("/api/families/{family_id}/expenses", response_model=ExpenseOut)
def create_expense(
    family_id: UUID,
    data: ExpenseCreate,
    user: User = Depends(get_current_user),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> ExpenseOut:
    family = family_service.get_family(db, family_id)
    return expense_service.create_expense(db, family, user, data)


@router.get("/api/families/{family_id}/expenses", response_model=list[ExpenseOut])
def list_expenses(
    family_id: UUID,
    month: str = Query(..., description="YYYY-MM in the family timezone"),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> list[ExpenseOut]:
    family = family_service.get_family(db, family_id)
    return expense_service.list_expenses(db, family, month=month)


@router.get("/api/families/{family_id}/spend", response_model=HouseholdSpendOut)
def household_spend(
    family_id: UUID,
    months: int = Query(default=12, ge=1, le=36),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> HouseholdSpendOut:
    family = family_service.get_family(db, family_id)
    return expense_service.get_spend(db, family, months=months)


@router.patch("/api/expenses/{expense_id}", response_model=ExpenseOut)
def patch_expense(
    expense_id: UUID,
    data: ExpenseUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExpenseOut:
    expense = expense_service.get_expense(db, expense_id)
    get_membership(db, expense.family_id, user.id)
    return expense_service.update_expense(db, expense, data)


@router.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(
    expense_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    expense = expense_service.get_expense(db, expense_id)
    get_membership(db, expense.family_id, user.id)
    expense_service.delete_expense(db, expense)
