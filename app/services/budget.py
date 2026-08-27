from __future__ import annotations

from datetime import date, datetime, timezone
import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from app.core.exceptions import bad_request, not_found
from app.core.money import as_money
from app.core.timeutil import (
    ensure_aware,
    family_today,
    family_zone,
    period_bounds,
)
from app.models.budget import Budget, BudgetAlert, BudgetPeriod
from app.models.budget_group import (
    BUDGET_GROUPS,
    GROUP_DIRECTIONS,
    GROUP_INCOME,
    OUTFLOW_GROUPS,
    is_inflow_group,
)
from app.models.budget_subcategory import BudgetSubcategory
from app.models.expense import SOURCE_BUDGET_LINE, Expense
from app.models.family import Family
from app.models.user import User, utcnow
from app.realtime.hub import hub
from app.services import budget_subcategory as subcategory_service
from app.services import notifications as notification_service
from app.schemas.budget import (
    BudgetGroupOut,
    BudgetInsightsMonthOut,
    BudgetInsightsOut,
    BudgetLineIn,
    BudgetOut,
    BudgetPeriodCopy,
    BudgetPeriodCreate,
    BudgetPeriodListOut,
    BudgetPeriodOut,
    BudgetPeriodSummaryOut,
    BudgetPeriodUpdate,
    BudgetState,
    BudgetSummaryOut,
    BudgetUpdate,
)

logger = logging.getLogger(__name__)

THRESHOLD_WARNING = 80
THRESHOLD_OVER = 100
_ZERO = Decimal("0.00")


def period_usage(
    db: Session,
    family: Family,
    period: BudgetPeriod,
) -> tuple[dict[UUID, Decimal], dict[UUID, UUID]]:
    """Return (used_by_subcategory_id, settlement_expense_id_by_budget_id)."""
    start, end = period_bounds(family.timezone, period.start_date, period.end_date)
    rows = (
        db.query(Expense.subcategory_id, func.sum(Expense.amount))
        .filter(
            Expense.family_id == family.id,
            Expense.occurred_at >= start,
            Expense.occurred_at < end,
        )
        .group_by(Expense.subcategory_id)
        .all()
    )
    used: dict[UUID, Decimal] = {sub_id: as_money(total) for sub_id, total in rows}

    budget_ids = [b.id for b in period.budgets]
    settlements: dict[UUID, UUID] = {}
    if budget_ids:
        settlement_rows = (
            db.query(Expense.source_id, Expense.id)
            .filter(
                Expense.source_type == SOURCE_BUDGET_LINE,
                Expense.source_id.in_(budget_ids),
            )
            .all()
        )
        settlements = {source_id: expense_id for source_id, expense_id in settlement_rows if source_id}
    return used, settlements


def derive_state(used: Decimal, amount: Decimal) -> tuple[int, BudgetState]:
    if amount <= 0:
        return 0, "ok"
    percent = int((used / amount * 100).quantize(Decimal("1")))
    if percent >= THRESHOLD_OVER:
        return percent, "over"
    if percent >= THRESHOLD_WARNING:
        return percent, "warning"
    return percent, "ok"


def default_label_month(end_date: date) -> str:
    return f"{end_date.year:04d}-{end_date.month:02d}"


def current_period(
    db: Session,
    family: Family,
    *,
    on: date | None = None,
) -> BudgetPeriod | None:
    day = on or family_today(family.timezone)
    return (
        db.query(BudgetPeriod)
        .options(joinedload(BudgetPeriod.budgets))
        .filter(
            BudgetPeriod.family_id == family.id,
            BudgetPeriod.start_date <= day,
            BudgetPeriod.end_date >= day,
        )
        .order_by(BudgetPeriod.start_date.desc())
        .first()
    )


def period_for_expense_at(
    db: Session,
    family: Family,
    occurred_at: datetime,
) -> BudgetPeriod | None:
    local = ensure_aware(occurred_at).astimezone(family_zone(family.timezone))
    return current_period(db, family, on=local.date())


def get_period(db: Session, period_id: UUID) -> BudgetPeriod:
    period = (
        db.query(BudgetPeriod)
        .options(joinedload(BudgetPeriod.budgets))
        .filter(BudgetPeriod.id == period_id)
        .first()
    )
    if period is None:
        raise not_found("Budget period not found")
    return period


def get_budget(db: Session, budget_id: UUID) -> Budget:
    budget = db.get(Budget, budget_id)
    if budget is None:
        raise not_found("Budget not found")
    return budget


def _periods_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end


def _assert_no_overlap(
    db: Session,
    family_id: UUID,
    start_date: date,
    end_date: date,
    *,
    exclude_period_id: UUID | None = None,
) -> None:
    query = db.query(BudgetPeriod).filter(BudgetPeriod.family_id == family_id)
    if exclude_period_id is not None:
        query = query.filter(BudgetPeriod.id != exclude_period_id)
    for other in query.all():
        if _periods_overlap(start_date, end_date, other.start_date, other.end_date):
            raise bad_request(
                f"Budget period overlaps existing cycle "
                f"({other.start_date.isoformat()} – {other.end_date.isoformat()})"
            )


def _load_subcategories(
    db: Session,
    subcategory_ids: set[UUID],
) -> dict[UUID, BudgetSubcategory]:
    if not subcategory_ids:
        return {}
    rows = db.query(BudgetSubcategory).filter(BudgetSubcategory.id.in_(subcategory_ids)).all()
    return {row.id: row for row in rows}


def budget_to_out(
    budget: Budget,
    *,
    family_id: UUID,
    currency: str,
    used: Decimal,
    subcategory: BudgetSubcategory,
    settlement_expense_id: UUID | None,
) -> BudgetOut:
    amount = as_money(budget.amount)
    used_money = as_money(used)
    percent_used, state = derive_state(used_money, amount)
    remaining = as_money(amount - used_money)
    return BudgetOut(
        id=budget.id,
        period_id=budget.period_id,
        family_id=family_id,
        subcategory_id=budget.subcategory_id,
        subcategory_name=subcategory.name,
        group=subcategory.group,
        amount=amount,
        currency=currency,
        used=used_money,
        remaining=remaining,
        percent_used=percent_used,
        state=state,
        settled=settlement_expense_id is not None,
        settlement_expense_id=settlement_expense_id,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


def _empty_summary() -> BudgetPeriodSummaryOut:
    return BudgetPeriodSummaryOut(
        income_expected=_ZERO,
        income_actual=_ZERO,
        total_expenses_expected=_ZERO,
        total_expenses_actual=_ZERO,
        left_over_expected=_ZERO,
        left_over_actual=_ZERO,
    )


def period_to_out(db: Session, family: Family, period: BudgetPeriod) -> BudgetPeriodOut:
    used_map, settlements = period_usage(db, family, period)
    sub_ids = {b.subcategory_id for b in period.budgets}
    # Also include subcategories that have spend but no budget line
    sub_ids.update(used_map.keys())
    subcats = _load_subcategories(db, sub_ids)

    lines_by_group: dict[str, list[BudgetOut]] = {g: [] for g in BUDGET_GROUPS}
    expected_by_group: dict[str, Decimal] = {g: _ZERO for g in BUDGET_GROUPS}
    actual_by_group: dict[str, Decimal] = {g: _ZERO for g in BUDGET_GROUPS}

    for budget in period.budgets:
        sub = subcats.get(budget.subcategory_id)
        if sub is None:
            continue
        used = used_map.get(budget.subcategory_id, _ZERO)
        out = budget_to_out(
            budget,
            family_id=family.id,
            currency=period.currency,
            used=used,
            subcategory=sub,
            settlement_expense_id=settlements.get(budget.id),
        )
        group = sub.group
        if group not in lines_by_group:
            lines_by_group[group] = []
            expected_by_group[group] = _ZERO
            actual_by_group[group] = _ZERO
        lines_by_group[group].append(out)
        expected_by_group[group] = as_money(expected_by_group[group] + out.amount)
        actual_by_group[group] = as_money(actual_by_group[group] + used)

    # Actual spend on subcategories with no budget line still rolls into group totals
    budgeted_sub_ids = {b.subcategory_id for b in period.budgets}
    for sub_id, used in used_map.items():
        if sub_id in budgeted_sub_ids:
            continue
        sub = subcats.get(sub_id)
        if sub is None:
            continue
        group = sub.group
        if group not in actual_by_group:
            actual_by_group[group] = _ZERO
            expected_by_group.setdefault(group, _ZERO)
            lines_by_group.setdefault(group, [])
        actual_by_group[group] = as_money(actual_by_group[group] + used)

    groups: list[BudgetGroupOut] = []
    for group in BUDGET_GROUPS:
        lines = sorted(lines_by_group.get(group, []), key=lambda line: line.subcategory_name.lower())
        groups.append(
            BudgetGroupOut(
                group=group,
                direction=GROUP_DIRECTIONS[group],
                expected=as_money(expected_by_group.get(group, _ZERO)),
                actual=as_money(actual_by_group.get(group, _ZERO)),
                lines=lines,
            )
        )

    income_expected = expected_by_group.get(GROUP_INCOME, _ZERO)
    income_actual = actual_by_group.get(GROUP_INCOME, _ZERO)
    total_expenses_expected = sum(
        (expected_by_group.get(g, _ZERO) for g in OUTFLOW_GROUPS),
        _ZERO,
    )
    total_expenses_actual = sum(
        (actual_by_group.get(g, _ZERO) for g in OUTFLOW_GROUPS),
        _ZERO,
    )
    summary = BudgetPeriodSummaryOut(
        income_expected=as_money(income_expected),
        income_actual=as_money(income_actual),
        total_expenses_expected=as_money(total_expenses_expected),
        total_expenses_actual=as_money(total_expenses_actual),
        left_over_expected=as_money(income_expected - total_expenses_expected),
        left_over_actual=as_money(income_actual - total_expenses_actual),
    )

    return BudgetPeriodOut(
        id=period.id,
        family_id=period.family_id,
        start_date=period.start_date,
        end_date=period.end_date,
        label_month=period.label_month,
        currency=period.currency,
        groups=groups,
        summary=summary,
        created_at=period.created_at,
        updated_at=period.updated_at,
    )


def overall_budget_summary(db: Session, family: Family) -> BudgetSummaryOut | None:
    """Household outflow guardrail for dashboard /spend strip."""
    period = current_period(db, family)
    if period is None:
        return None
    out = period_to_out(db, family, period)
    amount = out.summary.total_expenses_expected
    used = out.summary.total_expenses_actual
    if amount <= 0 and used <= 0:
        return None
    # When no expected outflow is set, still surface actual spend against amount=used
    effective_amount = amount if amount > 0 else used
    percent_used, state = derive_state(used, effective_amount if effective_amount > 0 else Decimal("0.01"))
    return BudgetSummaryOut(
        period_id=period.id,
        label_month=period.label_month,
        start_date=period.start_date,
        end_date=period.end_date,
        amount=as_money(effective_amount),
        used=as_money(used),
        remaining=as_money(effective_amount - used),
        percent_used=percent_used,
        state=state,
    )


def get_current_period_out(db: Session, family: Family) -> BudgetPeriodOut | None:
    period = current_period(db, family)
    if period is None:
        return None
    return period_to_out(db, family, period)


def list_periods(
    db: Session,
    family: Family,
    *,
    include: str = "current,past",
) -> BudgetPeriodListOut:
    today = family_today(family.timezone)
    tokens = {t.strip().lower() for t in include.split(",") if t.strip()}
    if not tokens:
        tokens = {"current", "past"}

    clauses = []
    if "current" in tokens:
        clauses.append(and_(BudgetPeriod.start_date <= today, BudgetPeriod.end_date >= today))
    if "upcoming" in tokens:
        clauses.append(BudgetPeriod.start_date > today)
    if "past" in tokens:
        clauses.append(BudgetPeriod.end_date < today)

    if not clauses:
        return BudgetPeriodListOut(periods=[])

    rows = (
        db.query(BudgetPeriod)
        .options(joinedload(BudgetPeriod.budgets))
        .filter(BudgetPeriod.family_id == family.id, or_(*clauses))
        .order_by(BudgetPeriod.start_date.desc())
        .all()
    )
    return BudgetPeriodListOut(periods=[period_to_out(db, family, p) for p in rows])


def _dedupe_budget_lines(lines: list[BudgetLineIn]) -> list[BudgetLineIn]:
    seen: set[UUID] = set()
    result: list[BudgetLineIn] = []
    for line in lines:
        if line.subcategory_id in seen:
            raise bad_request("Duplicate budget subcategory in request")
        seen.add(line.subcategory_id)
        result.append(line)
    return result


def _validate_subcategories(db: Session, family_id: UUID, lines: list[BudgetLineIn]) -> None:
    if not lines:
        return
    ids = {line.subcategory_id for line in lines}
    rows = (
        db.query(BudgetSubcategory)
        .filter(
            BudgetSubcategory.id.in_(ids),
            BudgetSubcategory.family_id == family_id,
            BudgetSubcategory.archived_at.is_(None),
        )
        .all()
    )
    found = {row.id for row in rows}
    missing = ids - found
    if missing:
        raise bad_request("One or more budget subcategories are invalid")


def _replace_period_budgets(db: Session, period: BudgetPeriod, lines: list[BudgetLineIn]) -> None:
    deduped = _dedupe_budget_lines(lines)
    _validate_subcategories(db, period.family_id, deduped)
    for existing in list(period.budgets):
        db.delete(existing)
    db.flush()
    for line in deduped:
        db.add(
            Budget(
                period_id=period.id,
                subcategory_id=line.subcategory_id,
                amount=line.amount,
            )
        )


def _broadcast_period(family_id: UUID, period_out: BudgetPeriodOut) -> None:
    hub.broadcast(
        family_id,
        {
            "type": "budget.updated",
            "period": period_out.model_dump(mode="json"),
        },
    )


def create_period(
    db: Session,
    family: Family,
    user: User,
    data: BudgetPeriodCreate,
) -> BudgetPeriodOut:
    subcategory_service.ensure_family_subcategories(db, family.id)
    _assert_no_overlap(db, family.id, data.start_date, data.end_date)
    label = data.label_month or default_label_month(data.end_date)
    period = BudgetPeriod(
        family_id=family.id,
        start_date=data.start_date,
        end_date=data.end_date,
        label_month=label,
        currency=data.currency,
        created_by=user.id,
    )
    db.add(period)
    db.flush()
    _replace_period_budgets(db, period, data.budgets)
    db.commit()
    period = get_period(db, period.id)
    out = period_to_out(db, family, period)
    _broadcast_period(family.id, out)
    return out


def update_period(
    db: Session,
    family: Family,
    period: BudgetPeriod,
    data: BudgetPeriodUpdate,
) -> BudgetPeriodOut:
    start = data.start_date if data.start_date is not None else period.start_date
    end = data.end_date if data.end_date is not None else period.end_date
    if end < start:
        raise bad_request("end_date must be on or after start_date")
    _assert_no_overlap(db, family.id, start, end, exclude_period_id=period.id)

    period.start_date = start
    period.end_date = end
    if data.label_month is not None:
        period.label_month = data.label_month
    elif data.end_date is not None and data.label_month is None:
        period.label_month = default_label_month(end)
    period.updated_at = utcnow()

    if data.budgets is not None:
        _replace_period_budgets(db, period, data.budgets)

    db.commit()
    period = get_period(db, period.id)
    out = period_to_out(db, family, period)
    _broadcast_period(family.id, out)
    return out


def copy_period(
    db: Session,
    family: Family,
    user: User,
    data: BudgetPeriodCopy,
) -> BudgetPeriodOut:
    subcategory_service.ensure_family_subcategories(db, family.id)
    source: BudgetPeriod | None = None
    if data.source_period_id is not None:
        source = get_period(db, data.source_period_id)
        if source.family_id != family.id:
            raise not_found("Budget period not found")
    else:
        source = (
            db.query(BudgetPeriod)
            .options(joinedload(BudgetPeriod.budgets))
            .filter(BudgetPeriod.family_id == family.id)
            .order_by(BudgetPeriod.end_date.desc())
            .first()
        )
    lines: list[BudgetLineIn] = []
    if source is not None:
        lines = [
            BudgetLineIn(subcategory_id=b.subcategory_id, amount=as_money(b.amount))
            for b in source.budgets
        ]
    return create_period(
        db,
        family,
        user,
        BudgetPeriodCreate(
            start_date=data.start_date,
            end_date=data.end_date,
            label_month=data.label_month,
            budgets=lines,
        ),
    )


def delete_period(db: Session, period: BudgetPeriod) -> None:
    period_id = period.id
    family_id = period.family_id
    db.delete(period)
    db.commit()
    hub.broadcast(
        family_id,
        {"type": "budget.deleted", "period_id": str(period_id)},
    )


def update_budget(db: Session, family: Family, budget: Budget, data: BudgetUpdate) -> BudgetOut:
    period = get_period(db, budget.period_id)
    if period.family_id != family.id:
        raise not_found("Budget not found")
    budget.amount = data.amount
    budget.updated_at = utcnow()
    db.commit()
    db.refresh(budget)
    used_map, settlements = period_usage(db, family, period)
    sub = subcategory_service.get_subcategory_any(db, budget.subcategory_id)
    out = budget_to_out(
        budget,
        family_id=family.id,
        currency=period.currency,
        used=used_map.get(budget.subcategory_id, _ZERO),
        subcategory=sub,
        settlement_expense_id=settlements.get(budget.id),
    )
    period_out = period_to_out(db, family, get_period(db, period.id))
    _broadcast_period(family.id, period_out)
    return out


def delete_budget(db: Session, budget: Budget) -> None:
    period = get_period(db, budget.period_id)
    family_id = period.family_id
    budget_id = budget.id
    # Remove settlement entry if present
    settlement = (
        db.query(Expense)
        .filter(Expense.source_type == SOURCE_BUDGET_LINE, Expense.source_id == budget_id)
        .first()
    )
    if settlement is not None:
        db.delete(settlement)
    db.delete(budget)
    db.commit()
    hub.broadcast(
        family_id,
        {"type": "budget.deleted", "budget_id": str(budget_id)},
    )
    family = db.get(Family, family_id)
    if family is not None:
        try:
            refreshed = get_period(db, period.id)
            _broadcast_period(family_id, period_to_out(db, family, refreshed))
        except Exception:  # noqa: BLE001
            pass


def settle_budget(
    db: Session,
    family: Family,
    user: User,
    budget: Budget,
) -> BudgetPeriodOut:
    period = get_period(db, budget.period_id)
    if period.family_id != family.id:
        raise not_found("Budget not found")
    existing = (
        db.query(Expense)
        .filter(Expense.source_type == SOURCE_BUDGET_LINE, Expense.source_id == budget.id)
        .first()
    )
    if existing is not None:
        return period_to_out(db, family, period)

    sub = subcategory_service.get_subcategory_any(db, budget.subcategory_id)
    # Settle on the period end date at noon family-local so it falls inside the cycle
    zone = family_zone(family.timezone)
    occurred_at = datetime(
        period.end_date.year,
        period.end_date.month,
        period.end_date.day,
        12,
        0,
        tzinfo=zone,
    )
    expense = Expense(
        family_id=family.id,
        amount=as_money(budget.amount),
        currency=period.currency,
        subcategory_id=budget.subcategory_id,
        merchant=None,
        note=f"Settled: {sub.name}",
        occurred_at=occurred_at,
        created_by=user.id,
        source_type=SOURCE_BUDGET_LINE,
        source_id=budget.id,
    )
    db.add(expense)
    db.commit()
    out = period_to_out(db, family, get_period(db, period.id))
    _broadcast_period(family.id, out)
    if not is_inflow_group(sub.group):
        safe_evaluate_budget_alerts(db, family.id, actor_user_id=user.id, as_of=period.end_date)
    return out


def unsettle_budget(
    db: Session,
    family: Family,
    budget: Budget,
) -> BudgetPeriodOut:
    period = get_period(db, budget.period_id)
    if period.family_id != family.id:
        raise not_found("Budget not found")
    existing = (
        db.query(Expense)
        .filter(Expense.source_type == SOURCE_BUDGET_LINE, Expense.source_id == budget.id)
        .first()
    )
    if existing is not None:
        db.delete(existing)
        db.commit()
        safe_recover_budget_alerts(db, family.id, as_of=period.end_date)
    out = period_to_out(db, family, get_period(db, period.id))
    _broadcast_period(family.id, out)
    return out


def _scope_label(subcategory: BudgetSubcategory) -> str:
    return f"{subcategory.group} · {subcategory.name}"


def _alert_exists(db: Session, budget_id: UUID, threshold: int) -> bool:
    return (
        db.query(BudgetAlert)
        .filter(BudgetAlert.budget_id == budget_id, BudgetAlert.threshold == threshold)
        .first()
        is not None
    )


def _record_alert(db: Session, budget_id: UUID, threshold: int) -> None:
    if _alert_exists(db, budget_id, threshold):
        return
    db.add(
        BudgetAlert(
            budget_id=budget_id,
            threshold=threshold,
            notified_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def _clear_alerts_below(db: Session, budget_id: UUID, percent_used: int) -> None:
    thresholds = [t for t in (80, 100) if percent_used < t]
    if not thresholds:
        return
    (
        db.query(BudgetAlert)
        .filter(
            BudgetAlert.budget_id == budget_id,
            BudgetAlert.threshold.in_(thresholds),
        )
        .delete(synchronize_session=False)
    )
    db.commit()


def _send_budget_notification(
    db: Session,
    *,
    family: Family,
    budget: Budget,
    subcategory: BudgetSubcategory,
    used: Decimal,
    threshold: int,
    actor_user_id: UUID | None,
    period: BudgetPeriod,
) -> None:
    scope = _scope_label(subcategory)
    amount = as_money(budget.amount)
    used_money = as_money(used)
    if threshold >= 100 and used_money > amount:
        over = as_money(used_money - amount)
        title = "Over budget"
        body = f"{scope} is €{over} over the €{amount} limit"
    else:
        title = "Budget warning"
        body = f"{scope}: €{used_money} of €{amount} used"

    notification_service.notify_family_members(
        db,
        family_id=family.id,
        actor_user_id=actor_user_id or period.created_by,
        pref_field="budget_alerts",
        type="budget",
        title=title,
        body=body,
        entity_type="budget",
        entity_id=budget.id,
        include_actor=True,
        family_timezone=family.timezone,
    )


def recover_budget_alerts(
    db: Session,
    family_id: UUID,
    *,
    as_of: date | None = None,
) -> None:
    family = db.get(Family, family_id)
    if family is None:
        return
    period = current_period(db, family, on=as_of)
    if period is None:
        return
    used_map, _ = period_usage(db, family, period)
    subcats = _load_subcategories(db, {b.subcategory_id for b in period.budgets})
    for budget in period.budgets:
        sub = subcats.get(budget.subcategory_id)
        if sub is None or is_inflow_group(sub.group):
            continue
        used = used_map.get(budget.subcategory_id, _ZERO)
        percent_used, _ = derive_state(used, as_money(budget.amount))
        _clear_alerts_below(db, budget.id, percent_used)


def evaluate_budget_alerts(
    db: Session,
    family_id: UUID,
    *,
    as_of: date | None = None,
    actor_user_id: UUID | None = None,
) -> None:
    family = db.get(Family, family_id)
    if family is None:
        return
    period = current_period(db, family, on=as_of)
    if period is None:
        return
    used_map, _ = period_usage(db, family, period)
    subcats = _load_subcategories(db, {b.subcategory_id for b in period.budgets})
    for budget in period.budgets:
        sub = subcats.get(budget.subcategory_id)
        if sub is None or is_inflow_group(sub.group):
            continue
        used = used_map.get(budget.subcategory_id, _ZERO)
        amount = as_money(budget.amount)
        percent_used, _ = derive_state(used, amount)

        notify_threshold: int | None = None
        for threshold in (100, 80):
            if percent_used >= threshold and not _alert_exists(db, budget.id, threshold):
                notify_threshold = threshold
                break

        if notify_threshold is None:
            continue

        _send_budget_notification(
            db,
            family=family,
            budget=budget,
            subcategory=sub,
            used=used,
            threshold=notify_threshold,
            actor_user_id=actor_user_id,
            period=period,
        )
        _record_alert(db, budget.id, notify_threshold)
        if notify_threshold == 100 and not _alert_exists(db, budget.id, 80):
            _record_alert(db, budget.id, 80)


def safe_evaluate_budget_alerts(
    db: Session,
    family_id: UUID,
    *,
    actor_user_id: UUID | None = None,
    as_of: date | None = None,
    occurred_at: datetime | None = None,
) -> None:
    try:
        family = db.get(Family, family_id)
        day = as_of
        if day is None and occurred_at is not None and family is not None:
            day = ensure_aware(occurred_at).astimezone(family_zone(family.timezone)).date()
        evaluate_budget_alerts(db, family_id, as_of=day, actor_user_id=actor_user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Budget alert evaluation failed for family %s", family_id)


def safe_recover_budget_alerts(
    db: Session,
    family_id: UUID,
    *,
    as_of: date | None = None,
    occurred_at: datetime | None = None,
) -> None:
    try:
        family = db.get(Family, family_id)
        day = as_of
        if day is None and occurred_at is not None and family is not None:
            day = ensure_aware(occurred_at).astimezone(family_zone(family.timezone)).date()
        recover_budget_alerts(db, family_id, as_of=day)
    except Exception:  # noqa: BLE001
        logger.exception("Budget alert recovery failed for family %s", family_id)


def get_insights(db: Session, family: Family, *, months: int = 12) -> BudgetInsightsOut:
    from app.core.timeutil import add_calendar_months, family_now

    subcategory_service.ensure_family_subcategories(db, family.id)
    now = family_now(family.timezone)
    start_year, start_month = add_calendar_months(now.year, now.month, -(months - 1))

    periods = (
        db.query(BudgetPeriod)
        .options(joinedload(BudgetPeriod.budgets))
        .filter(BudgetPeriod.family_id == family.id)
        .order_by(BudgetPeriod.start_date.desc())
        .all()
    )
    by_label = {p.label_month: p for p in periods}

    month_rows: list[BudgetInsightsMonthOut] = []
    currency = "EUR"
    for i in range(months):
        year, month = add_calendar_months(start_year, start_month, i)
        key = f"{year:04d}-{month:02d}"
        period = by_label.get(key)
        if period is not None:
            out = period_to_out(db, family, period)
            currency = out.currency
            month_rows.append(
                BudgetInsightsMonthOut(
                    month=key,
                    income_expected=out.summary.income_expected,
                    income_actual=out.summary.income_actual,
                    outflow_expected=out.summary.total_expenses_expected,
                    outflow_actual=out.summary.total_expenses_actual,
                    net_expected=out.summary.left_over_expected,
                    net_actual=out.summary.left_over_actual,
                    groups=out.groups,
                )
            )
            continue

        # No planned period: still show actual ledger for that calendar month
        from app.core.timeutil import month_bounds

        start, end = month_bounds(family.timezone, year, month)
        rows = (
            db.query(BudgetSubcategory.group, func.sum(Expense.amount))
            .join(Expense, Expense.subcategory_id == BudgetSubcategory.id)
            .filter(
                Expense.family_id == family.id,
                Expense.occurred_at >= start,
                Expense.occurred_at < end,
            )
            .group_by(BudgetSubcategory.group)
            .all()
        )
        actual_by_group = {g: as_money(total) for g, total in rows}
        groups = [
            BudgetGroupOut(
                group=group,
                direction=GROUP_DIRECTIONS[group],
                expected=_ZERO,
                actual=as_money(actual_by_group.get(group, _ZERO)),
                lines=[],
            )
            for group in BUDGET_GROUPS
        ]
        income_actual = actual_by_group.get(GROUP_INCOME, _ZERO)
        outflow_actual = sum((actual_by_group.get(g, _ZERO) for g in OUTFLOW_GROUPS), _ZERO)
        month_rows.append(
            BudgetInsightsMonthOut(
                month=key,
                income_expected=_ZERO,
                income_actual=as_money(income_actual),
                outflow_expected=_ZERO,
                outflow_actual=as_money(outflow_actual),
                net_expected=_ZERO,
                net_actual=as_money(income_actual - outflow_actual),
                groups=groups,
            )
        )

    return BudgetInsightsOut(currency=currency, months=month_rows)
