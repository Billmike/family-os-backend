from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.personal_expense import (
    PersonalAccountCreate,
    PersonalAccountListOut,
    PersonalAccountOut,
    PersonalAccountUpdate,
    PersonalExpenseCreate,
    PersonalExpenseOut,
    PersonalExpenseUpdate,
)
from app.services import personal_expense as personal_expense_service

router = APIRouter(tags=["personal-expenses"])


@router.get("/api/me/expense-accounts", response_model=PersonalAccountListOut)
def list_accounts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PersonalAccountListOut:
    return personal_expense_service.list_accounts(db, user)


@router.post("/api/me/expense-accounts", response_model=PersonalAccountOut)
def create_account(
    data: PersonalAccountCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PersonalAccountOut:
    return personal_expense_service.create_account(db, user, data)


@router.patch("/api/me/expense-accounts/{account_id}", response_model=PersonalAccountOut)
def patch_account(
    account_id: UUID,
    data: PersonalAccountUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PersonalAccountOut:
    return personal_expense_service.update_account(db, user, account_id, data)


@router.delete("/api/me/expense-accounts/{account_id}", status_code=204)
def delete_account(
    account_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    personal_expense_service.delete_account(db, user, account_id)


@router.get(
    "/api/me/expense-accounts/{account_id}/expenses",
    response_model=list[PersonalExpenseOut],
)
def list_account_expenses(
    account_id: UUID,
    month: str = Query(..., description="YYYY-MM in the user's timezone"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PersonalExpenseOut]:
    return personal_expense_service.list_expenses(db, user, account_id, month=month)


@router.post(
    "/api/me/expense-accounts/{account_id}/expenses",
    response_model=PersonalExpenseOut,
)
def create_account_expense(
    account_id: UUID,
    data: PersonalExpenseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PersonalExpenseOut:
    return personal_expense_service.create_expense(db, user, account_id, data)


@router.patch("/api/personal-expenses/{expense_id}", response_model=PersonalExpenseOut)
def patch_personal_expense(
    expense_id: UUID,
    data: PersonalExpenseUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PersonalExpenseOut:
    return personal_expense_service.update_expense(db, user, expense_id, data)


@router.delete("/api/personal-expenses/{expense_id}", status_code=204)
def delete_personal_expense(
    expense_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    personal_expense_service.delete_expense(db, user, expense_id)
