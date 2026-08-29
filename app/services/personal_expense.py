from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, conflict, not_found
from app.core.money import as_money
from app.core.timeutil import family_now, month_bounds, parse_year_month
from app.models.personal_expense import PersonalExpense, PersonalExpenseAccount
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

_ZERO = Decimal("0.00")


def user_timezone(user: User) -> str:
    tz = (user.timezone or "").strip()
    return tz if tz else "UTC"


def ensure_user_timezone(user: User, tz_name: str | None) -> None:
    if user.timezone:
        return
    stripped = (tz_name or "").strip()
    if stripped:
        user.timezone = stripped


def _current_month_window(user: User) -> tuple[str, datetime, datetime]:
    tz = user_timezone(user)
    now = family_now(tz)
    current_month = f"{now.year:04d}-{now.month:02d}"
    start, end = month_bounds(tz, now.year, now.month)
    return current_month, start, end


def get_owned_account(db: Session, user: User, account_id: UUID) -> PersonalExpenseAccount:
    account = db.get(PersonalExpenseAccount, account_id)
    if account is None or account.user_id != user.id:
        raise not_found("Expense account not found")
    return account


def get_owned_expense(db: Session, user: User, expense_id: UUID) -> PersonalExpense:
    expense = (
        db.query(PersonalExpense)
        .join(PersonalExpenseAccount, PersonalExpenseAccount.id == PersonalExpense.account_id)
        .filter(PersonalExpense.id == expense_id, PersonalExpenseAccount.user_id == user.id)
        .first()
    )
    if expense is None:
        raise not_found("Expense not found")
    return expense


def account_to_out(
    account: PersonalExpenseAccount,
    *,
    month_total: Decimal = _ZERO,
    month_count: int = 0,
) -> PersonalAccountOut:
    return PersonalAccountOut(
        id=account.id,
        name=account.name,
        currency=account.currency,
        sort_order=account.sort_order,
        current_month_total=as_money(month_total),
        current_month_count=month_count,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


def expense_to_out(expense: PersonalExpense) -> PersonalExpenseOut:
    return PersonalExpenseOut(
        id=expense.id,
        account_id=expense.account_id,
        amount=as_money(expense.amount),
        currency=expense.currency,
        category=expense.category,
        merchant=expense.merchant,
        note=expense.note,
        occurred_at=expense.occurred_at,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )


def _month_totals(
    db: Session,
    account_ids: list[UUID],
    start: datetime,
    end: datetime,
) -> dict[UUID, tuple[Decimal, int]]:
    if not account_ids:
        return {}
    rows = (
        db.query(
            PersonalExpense.account_id,
            func.coalesce(func.sum(PersonalExpense.amount), _ZERO),
            func.count(PersonalExpense.id),
        )
        .filter(
            PersonalExpense.account_id.in_(account_ids),
            PersonalExpense.occurred_at >= start,
            PersonalExpense.occurred_at < end,
        )
        .group_by(PersonalExpense.account_id)
        .all()
    )
    return {account_id: (as_money(total), int(count)) for account_id, total, count in rows}


def list_accounts(db: Session, user: User) -> PersonalAccountListOut:
    current_month, start, end = _current_month_window(user)
    accounts = (
        db.query(PersonalExpenseAccount)
        .filter(PersonalExpenseAccount.user_id == user.id)
        .order_by(PersonalExpenseAccount.sort_order.asc(), PersonalExpenseAccount.created_at.asc())
        .all()
    )
    totals = _month_totals(db, [row.id for row in accounts], start, end)
    out_rows: list[PersonalAccountOut] = []
    grand_total = _ZERO
    grand_count = 0
    currency = "EUR"
    for account in accounts:
        month_total, month_count = totals.get(account.id, (_ZERO, 0))
        grand_total += month_total
        grand_count += month_count
        currency = account.currency or currency
        out_rows.append(account_to_out(account, month_total=month_total, month_count=month_count))
    return PersonalAccountListOut(
        timezone=user_timezone(user),
        current_month=current_month,
        current_month_total=as_money(grand_total),
        current_month_count=grand_count,
        currency=currency,
        accounts=out_rows,
    )


def create_account(db: Session, user: User, data: PersonalAccountCreate) -> PersonalAccountOut:
    ensure_user_timezone(user, data.timezone)
    max_order = (
        db.query(func.max(PersonalExpenseAccount.sort_order))
        .filter(PersonalExpenseAccount.user_id == user.id)
        .scalar()
    )
    next_order = (max_order + 1) if max_order is not None else 0
    account = PersonalExpenseAccount(
        user_id=user.id,
        name=data.name,
        currency=data.currency,
        sort_order=next_order,
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("An expense account with that name already exists")
    db.refresh(account)
    return account_to_out(account)


def update_account(
    db: Session, user: User, account_id: UUID, data: PersonalAccountUpdate
) -> PersonalAccountOut:
    account = get_owned_account(db, user, account_id)
    if data.name is not None:
        account.name = data.name
    if data.currency is not None:
        account.currency = data.currency
    account.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise conflict("An expense account with that name already exists")
    db.refresh(account)
    _, start, end = _current_month_window(user)
    totals = _month_totals(db, [account.id], start, end)
    month_total, month_count = totals.get(account.id, (_ZERO, 0))
    return account_to_out(account, month_total=month_total, month_count=month_count)


def delete_account(db: Session, user: User, account_id: UUID) -> None:
    account = get_owned_account(db, user, account_id)
    db.delete(account)
    db.commit()


def list_expenses(
    db: Session,
    user: User,
    account_id: UUID,
    *,
    month: str,
) -> list[PersonalExpenseOut]:
    get_owned_account(db, user, account_id)
    try:
        year, month_num = parse_year_month(month)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    start, end = month_bounds(user_timezone(user), year, month_num)
    rows = (
        db.query(PersonalExpense)
        .filter(
            PersonalExpense.account_id == account_id,
            PersonalExpense.occurred_at >= start,
            PersonalExpense.occurred_at < end,
        )
        .order_by(PersonalExpense.occurred_at.desc(), PersonalExpense.created_at.desc())
        .all()
    )
    return [expense_to_out(row) for row in rows]


def create_expense(
    db: Session, user: User, account_id: UUID, data: PersonalExpenseCreate
) -> PersonalExpenseOut:
    account = get_owned_account(db, user, account_id)
    occurred_at = data.occurred_at or datetime.now(timezone.utc)
    expense = PersonalExpense(
        account_id=account.id,
        amount=data.amount,
        currency=data.currency or account.currency,
        category=data.category,
        merchant=data.merchant,
        note=data.note,
        occurred_at=occurred_at,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense_to_out(expense)


def update_expense(
    db: Session, user: User, expense_id: UUID, data: PersonalExpenseUpdate
) -> PersonalExpenseOut:
    expense = get_owned_expense(db, user, expense_id)
    fields = data.model_fields_set
    if "amount" in fields and data.amount is not None:
        expense.amount = data.amount
    if "category" in fields and data.category is not None:
        expense.category = data.category
    if "merchant" in fields:
        expense.merchant = data.merchant
    if "note" in fields:
        expense.note = data.note
    if "occurred_at" in fields and data.occurred_at is not None:
        expense.occurred_at = data.occurred_at
    expense.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(expense)
    return expense_to_out(expense)


def delete_expense(db: Session, user: User, expense_id: UUID) -> None:
    expense = get_owned_expense(db, user, expense_id)
    db.delete(expense)
    db.commit()
