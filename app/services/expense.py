from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.money import as_money

from app.core.exceptions import bad_request, not_found
from app.core.timeutil import (
    add_calendar_months,
    ensure_aware,
    family_now,
    month_bounds,
    month_key,
    parse_year_month,
    period_bounds,
)
from app.services import budget as budget_service
from app.services import budget_subcategory as subcategory_service
from app.models.budget_group import GROUP_DIRECTIONS, OUTFLOW_GROUPS, is_outflow_group
from app.models.budget_subcategory import BudgetSubcategory
from app.models.expense import (
    SOURCE_MANUAL,
    SOURCE_RECEIPT,
    SOURCE_SHOPPING_SESSION,
    Expense,
)
from app.models.family import Family
from app.models.receipt import ReceiptItem
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

_ZERO = Decimal("0.00")


def _as_money(value: Decimal | None) -> Decimal:
    return as_money(value)


def _source_item_counts(db: Session, expenses: list[Expense]) -> dict[UUID, int]:
    session_ids = [
        expense.source_id
        for expense in expenses
        if expense.source_type == SOURCE_SHOPPING_SESSION and expense.source_id is not None
    ]
    receipt_ids = [
        expense.source_id
        for expense in expenses
        if expense.source_type == SOURCE_RECEIPT and expense.source_id is not None
    ]
    counts: dict[UUID, int] = {}
    if session_ids:
        rows = (
            db.query(ShoppingSessionItem.session_id, func.count(ShoppingSessionItem.id))
            .filter(ShoppingSessionItem.session_id.in_(session_ids))
            .group_by(ShoppingSessionItem.session_id)
            .all()
        )
        counts.update({session_id: int(count) for session_id, count in rows})
    if receipt_ids:
        rows = (
            db.query(ReceiptItem.receipt_id, func.count(ReceiptItem.id))
            .filter(
                ReceiptItem.receipt_id.in_(receipt_ids),
                ReceiptItem.is_included.is_(True),
            )
            .group_by(ReceiptItem.receipt_id)
            .all()
        )
        counts.update({receipt_id: int(count) for receipt_id, count in rows})
    return counts


def _subcategories_map(db: Session, expenses: list[Expense]) -> dict[UUID, BudgetSubcategory]:
    ids = {e.subcategory_id for e in expenses}
    if not ids:
        return {}
    rows = db.query(BudgetSubcategory).filter(BudgetSubcategory.id.in_(ids)).all()
    return {row.id: row for row in rows}


def expense_to_out(
    expense: Expense,
    *,
    subcategory: BudgetSubcategory,
    source_item_count: int | None = None,
) -> ExpenseOut:
    return ExpenseOut(
        id=expense.id,
        family_id=expense.family_id,
        amount=_as_money(expense.amount),
        currency=expense.currency,
        subcategory_id=expense.subcategory_id,
        subcategory_name=subcategory.name,
        group=subcategory.group,
        direction=GROUP_DIRECTIONS.get(subcategory.group, "outflow"),
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


def _broadcast(
    family_id: UUID,
    event_type: str,
    expense: Expense,
    *,
    subcategory: BudgetSubcategory,
    source_item_count: int | None,
) -> None:
    hub.broadcast(
        family_id,
        {
            "type": event_type,
            "expense": expense_to_out(
                expense, subcategory=subcategory, source_item_count=source_item_count
            ).model_dump(mode="json"),
        },
    )


def get_expense(db: Session, expense_id: UUID) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise not_found("Expense not found")
    return expense


_EDITABLE_SOURCES = (SOURCE_MANUAL, SOURCE_RECEIPT)


def _require_editable(expense: Expense) -> None:
    if expense.source_type not in _EDITABLE_SOURCES:
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
    groceries = subcategory_service.groceries_subcategory(db, session.family_id)
    occurred_at = session.completed_at or datetime.now(timezone.utc)
    expense = Expense(
        family_id=session.family_id,
        amount=session.total_cost,
        currency=session.currency or "EUR",
        subcategory_id=groceries.id,
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
    sub = subcategory_service.get_subcategory(db, data.subcategory_id)
    if sub.family_id != family.id:
        raise bad_request("Invalid budget subcategory")
    occurred_at = data.occurred_at or datetime.now(timezone.utc)
    expense = Expense(
        family_id=family.id,
        amount=data.amount,
        currency=data.currency,
        subcategory_id=data.subcategory_id,
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
    out = expense_to_out(expense, subcategory=sub, source_item_count=None)
    _broadcast(family.id, "expense.created", expense, subcategory=sub, source_item_count=None)
    if is_outflow_group(sub.group):
        budget_service.safe_evaluate_budget_alerts(
            db, family.id, actor_user_id=user.id, occurred_at=expense.occurred_at
        )
    return out


def _list_expenses_in_range(
    db: Session,
    family: Family,
    start: datetime,
    end: datetime,
) -> list[ExpenseOut]:
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
    subcats = _subcategories_map(db, rows)
    result: list[ExpenseOut] = []
    for expense in rows:
        sub = subcats.get(expense.subcategory_id)
        if sub is None:
            continue
        result.append(
            expense_to_out(
                expense,
                subcategory=sub,
                source_item_count=counts.get(expense.source_id) if expense.source_id else None,
            )
        )
    return result


def list_expenses(
    db: Session,
    family: Family,
    *,
    month: str | None = None,
    period_id: UUID | None = None,
) -> list[ExpenseOut]:
    has_month = month is not None and month.strip() != ""
    has_period = period_id is not None
    if has_month == has_period:
        raise bad_request("Provide exactly one of month or period_id")
    if has_period:
        assert period_id is not None
        period = budget_service.get_period(db, period_id)
        if period.family_id != family.id:
            raise not_found("Budget period not found")
        start, end = period_bounds(family.timezone, period.start_date, period.end_date)
        return _list_expenses_in_range(db, family, start, end)
    assert month is not None
    try:
        year, month_num = parse_year_month(month)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    start, end = month_bounds(family.timezone, year, month_num)
    return _list_expenses_in_range(db, family, start, end)


def update_expense(db: Session, expense: Expense, data: ExpenseUpdate) -> ExpenseOut:
    _require_editable(expense)
    fields = data.model_fields_set
    if "amount" in fields and data.amount is not None:
        expense.amount = data.amount
    if "subcategory_id" in fields and data.subcategory_id is not None:
        sub = subcategory_service.get_subcategory(db, data.subcategory_id)
        if sub.family_id != expense.family_id:
            raise bad_request("Invalid budget subcategory")
        expense.subcategory_id = data.subcategory_id
    if "merchant" in fields:
        expense.merchant = data.merchant
    if "note" in fields:
        expense.note = data.note
    if "occurred_at" in fields and data.occurred_at is not None:
        expense.occurred_at = data.occurred_at
    expense.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(expense)
    counts = _source_item_counts(db, [expense])
    count = counts.get(expense.source_id) if expense.source_id else None
    sub = subcategory_service.get_subcategory_any(db, expense.subcategory_id)
    out = expense_to_out(expense, subcategory=sub, source_item_count=count)
    _broadcast(expense.family_id, "expense.updated", expense, subcategory=sub, source_item_count=count)
    budget_service.safe_recover_budget_alerts(db, expense.family_id, occurred_at=expense.occurred_at)
    if is_outflow_group(sub.group):
        budget_service.safe_evaluate_budget_alerts(
            db, expense.family_id, actor_user_id=expense.created_by, occurred_at=expense.occurred_at
        )
    return out


def delete_expense(db: Session, expense: Expense) -> None:
    _require_editable(expense)
    expense_id = expense.id
    family_id = expense.family_id
    occurred_at = expense.occurred_at
    if expense.source_type == SOURCE_RECEIPT:
        from app.services import receipt as receipt_service

        receipt_service.delete_receipt_for_expense(db, expense)
    db.delete(expense)
    db.commit()
    hub.broadcast(
        family_id,
        {"type": "expense.deleted", "expense_id": str(expense_id)},
    )
    budget_service.safe_recover_budget_alerts(db, family_id, occurred_at=occurred_at)


def get_spend(
    db: Session,
    family: Family,
    *,
    months: int = 12,
    subcategory_id: UUID | None = None,
    groceries_only: bool = False,
) -> HouseholdSpendOut:
    """Aggregate outflow ledger entries. Income is excluded from spend charts."""
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

    query = (
        db.query(Expense, BudgetSubcategory)
        .join(BudgetSubcategory, BudgetSubcategory.id == Expense.subcategory_id)
        .filter(
            Expense.family_id == family.id,
            Expense.occurred_at >= query_start,
            BudgetSubcategory.group.in_(OUTFLOW_GROUPS),
        )
    )
    if subcategory_id is not None:
        query = query.filter(Expense.subcategory_id == subcategory_id)
    if groceries_only:
        groceries = subcategory_service.groceries_subcategory(db, family.id)
        query = query.filter(Expense.subcategory_id == groceries.id)

    pairs = query.all()

    totals: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    counts: dict[str, int] = defaultdict(int)
    category_totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: _ZERO))
    category_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    category_meta: dict[str, tuple[UUID, str]] = {}
    year_to_date = _ZERO
    currency = "EUR"
    latest_at: datetime | None = None

    for expense, sub in pairs:
        key = month_key(expense.occurred_at, family.timezone)
        cost = _as_money(expense.amount)
        label = f"{sub.group} · {sub.name}"
        category_meta[label] = (sub.id, sub.group)
        if key in window_keys:
            totals[key] += cost
            counts[key] += 1
            category_totals[key][label] += cost
            category_counts[key][label] += 1
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
                subcategory_id=category_meta[name][0],
                group=category_meta[name][1],
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
        budget=budget_service.overall_budget_summary(db, family),
    )
