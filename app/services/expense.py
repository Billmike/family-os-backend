from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, not_found
from app.core.timeutil import (
    add_calendar_months,
    ensure_aware,
    family_now,
    month_bounds,
    month_key,
    parse_year_month,
)
from app.models.expense import (
    CATEGORY_SHOPPING,
    SOURCE_MANUAL,
    SOURCE_SHOPPING_SESSION,
    Expense,
)
from app.models.family import Family
from app.models.shopping_session import ShoppingSession, ShoppingSessionItem
from app.models.user import User
from app.realtime.hub import hub
from app.schemas.expense import (
    CategorySpendOut,
    ExpenseCreate,
    ExpenseOut,
    ExpenseUpdate,
    HouseholdSpendOut,
    MonthlyHouseholdSpendOut,
)

_MONEY = Decimal("0.01")
_ZERO = Decimal("0.00")


def _as_money(value: Decimal | None) -> Decimal:
    amount = Decimal(str(value)) if value is not None else _ZERO
    return amount.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _source_item_counts(db: Session, expenses: list[Expense]) -> dict[UUID, int]:
    session_ids = [
        expense.source_id
        for expense in expenses
        if expense.source_type == SOURCE_SHOPPING_SESSION and expense.source_id is not None
    ]
    if not session_ids:
        return {}
    rows = (
        db.query(ShoppingSessionItem.session_id, func.count(ShoppingSessionItem.id))
        .filter(ShoppingSessionItem.session_id.in_(session_ids))
        .group_by(ShoppingSessionItem.session_id)
        .all()
    )
    return {session_id: int(count) for session_id, count in rows}


def expense_to_out(expense: Expense, *, source_item_count: int | None = None) -> ExpenseOut:
    return ExpenseOut(
        id=expense.id,
        family_id=expense.family_id,
        amount=_as_money(expense.amount),
        currency=expense.currency,
        category=expense.category,
        merchant=expense.merchant,
        note=expense.note,
        occurred_at=expense.occurred_at,
        created_by=expense.created_by,
        source_type=expense.source_type,
        source_id=expense.source_id,
        source_item_count=source_item_count,
        created_at=expense.created_at,
        updated_at=expense.updated_at,
    )


def _broadcast(family_id: UUID, event_type: str, expense: Expense, *, source_item_count: int | None) -> None:
    hub.broadcast(
        family_id,
        {
            "type": event_type,
            "expense": expense_to_out(expense, source_item_count=source_item_count).model_dump(mode="json"),
        },
    )


def get_expense(db: Session, expense_id: UUID) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise not_found("Expense not found")
    return expense


def _require_manual(expense: Expense) -> None:
    if expense.source_type != SOURCE_MANUAL:
        raise bad_request("Shopping trip expenses cannot be edited here")


def record_shopping_session_expense(
    db: Session,
    *,
    session: ShoppingSession,
    user: User,
) -> Expense:
    existing = (
        db.query(Expense)
        .filter(
            Expense.source_type == SOURCE_SHOPPING_SESSION,
            Expense.source_id == session.id,
        )
        .first()
    )
    if existing is not None:
        return existing
    if session.total_cost is None:
        raise bad_request("Shopping session has no total cost")
    occurred_at = session.completed_at or datetime.now(timezone.utc)
    expense = Expense(
        family_id=session.family_id,
        amount=session.total_cost,
        currency=session.currency or "EUR",
        category=CATEGORY_SHOPPING,
        merchant=None,
        note=None,
        occurred_at=occurred_at,
        created_by=user.id,
        source_type=SOURCE_SHOPPING_SESSION,
        source_id=session.id,
    )
    db.add(expense)
    return expense


def create_expense(db: Session, family: Family, user: User, data: ExpenseCreate) -> ExpenseOut:
    occurred_at = data.occurred_at or datetime.now(timezone.utc)
    expense = Expense(
        family_id=family.id,
        amount=data.amount,
        currency=data.currency,
        category=data.category,
        merchant=data.merchant,
        note=data.note,
        occurred_at=occurred_at,
        created_by=user.id,
        source_type=SOURCE_MANUAL,
        source_id=None,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    out = expense_to_out(expense, source_item_count=None)
    _broadcast(family.id, "expense.created", expense, source_item_count=None)
    return out


def list_expenses(
    db: Session,
    family: Family,
    *,
    month: str,
) -> list[ExpenseOut]:
    try:
        year, month_num = parse_year_month(month)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    start, end = month_bounds(family.timezone, year, month_num)
    rows = (
        db.query(Expense)
        .filter(
            Expense.family_id == family.id,
            Expense.occurred_at >= start,
            Expense.occurred_at < end,
        )
        .order_by(Expense.occurred_at.desc(), Expense.created_at.desc())
        .all()
    )
    counts = _source_item_counts(db, rows)
    return [
        expense_to_out(
            expense,
            source_item_count=counts.get(expense.source_id) if expense.source_id else None,
        )
        for expense in rows
    ]


def update_expense(db: Session, expense: Expense, data: ExpenseUpdate) -> ExpenseOut:
    _require_manual(expense)
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
    out = expense_to_out(expense, source_item_count=None)
    _broadcast(expense.family_id, "expense.updated", expense, source_item_count=None)
    return out


def delete_expense(db: Session, expense: Expense) -> None:
    _require_manual(expense)
    expense_id = expense.id
    family_id = expense.family_id
    db.delete(expense)
    db.commit()
    hub.broadcast(
        family_id,
        {"type": "expense.deleted", "expense_id": str(expense_id)},
    )


def get_spend(
    db: Session,
    family: Family,
    *,
    months: int = 12,
    category: str | None = None,
) -> HouseholdSpendOut:
    now = family_now(family.timezone)
    current_month = f"{now.year:04d}-{now.month:02d}"
    window_keys: list[str] = []
    start_year, start_month = add_calendar_months(now.year, now.month, -(months - 1))
    for i in range(months):
        year, month = add_calendar_months(start_year, start_month, i)
        window_keys.append(f"{year:04d}-{month:02d}")

    window_start, _ = month_bounds(family.timezone, start_year, start_month)
    year_start, _ = month_bounds(family.timezone, now.year, 1)
    query_start = window_start if window_start <= year_start else year_start

    query = db.query(Expense).filter(
        Expense.family_id == family.id,
        Expense.occurred_at >= query_start,
    )
    if category is not None:
        query = query.filter(Expense.category == category)
    expenses = query.all()

    totals: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    counts: dict[str, int] = defaultdict(int)
    category_totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: _ZERO))
    category_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    year_to_date = _ZERO
    currency = "EUR"
    latest_at: datetime | None = None

    for expense in expenses:
        key = month_key(expense.occurred_at, family.timezone)
        cost = _as_money(expense.amount)
        if key in window_keys:
            totals[key] += cost
            counts[key] += 1
            category_totals[key][expense.category] += cost
            category_counts[key][expense.category] += 1
        if key.startswith(f"{now.year:04d}-"):
            year_to_date += cost
        occurred = ensure_aware(expense.occurred_at)
        if latest_at is None or occurred > latest_at:
            latest_at = occurred
            currency = expense.currency or "EUR"

    month_rows: list[MonthlyHouseholdSpendOut] = []
    for key in window_keys:
        entry_count = counts[key]
        total = _as_money(totals[key])
        average = _as_money(total / entry_count) if entry_count else _ZERO
        cats = [
            CategorySpendOut(
                category=name,
                total=_as_money(cat_total),
                count=category_counts[key][name],
            )
            for name, cat_total in sorted(
                category_totals[key].items(),
                key=lambda item: (-item[1], item[0]),
            )
        ]
        month_rows.append(
            MonthlyHouseholdSpendOut(
                month=key,
                total=total,
                entry_count=entry_count,
                average=average,
                categories=cats,
            )
        )

    return HouseholdSpendOut(
        currency=currency,
        current_month=current_month,
        year_to_date_total=_as_money(year_to_date),
        months=month_rows,
    )
