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
from app.models.expense import Expense
from app.models.family import Family
from app.models.user import User, utcnow
from app.realtime.hub import hub
from app.services import notifications as notification_service
from app.schemas.budget import (
    BudgetLineIn,
    BudgetOut,
    BudgetPeriodCreate,
    BudgetPeriodListOut,
    BudgetPeriodOut,
    BudgetPeriodUpdate,
    BudgetState,
    BudgetSummaryOut,
    BudgetUpdate,
)

logger = logging.getLogger(__name__)

THRESHOLD_WARNING = 80
THRESHOLD_OVER = 100
_ZERO = Decimal("0.00")


def period_usage(db: Session, family: Family, period: BudgetPeriod) -> dict[str | None, Decimal]:
    """Return {category: total} for the period, plus None key for overall total."""
    start, end = period_bounds(family.timezone, period.start_date, period.end_date)
    rows = (
        db.query(Expense.category, func.sum(Expense.amount))
        .filter(
            Expense.family_id == family.id,
            Expense.occurred_at >= start,
            Expense.occurred_at < end,
        )
        .group_by(Expense.category)
        .all()
    )
    by_category: dict[str | None, Decimal] = {category: as_money(total) for category, total in rows}
    overall = sum(by_category.values(), _ZERO)
    by_category[None] = as_money(overall)
    return by_category


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


def budget_to_out(
    budget: Budget,
    *,
    family_id: UUID,
    currency: str,
    used: Decimal,
) -> BudgetOut:
    amount = as_money(budget.amount)
    used_money = as_money(used)
    percent_used, state = derive_state(used_money, amount)
    remaining = as_money(amount - used_money)
    return BudgetOut(
        id=budget.id,
        period_id=budget.period_id,
        family_id=family_id,
        category=budget.category,
        amount=amount,
        currency=currency,
        used=used_money,
        remaining=remaining,
        percent_used=percent_used,
        state=state,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


def period_to_out(db: Session, family: Family, period: BudgetPeriod) -> BudgetPeriodOut:
    usage = period_usage(db, family, period)
    overall_out: BudgetOut | None = None
    category_outs: list[BudgetOut] = []
    for budget in sorted(period.budgets, key=lambda b: (b.category is not None, b.category or "")):
        used = usage.get(budget.category, _ZERO)
        out = budget_to_out(
            budget,
            family_id=family.id,
            currency=period.currency,
            used=used,
        )
        if budget.category is None:
            overall_out = out
        else:
            category_outs.append(out)
    return BudgetPeriodOut(
        id=period.id,
        family_id=period.family_id,
        start_date=period.start_date,
        end_date=period.end_date,
        label_month=period.label_month,
        currency=period.currency,
        overall=overall_out,
        categories=category_outs,
        created_at=period.created_at,
        updated_at=period.updated_at,
    )


def overall_budget_summary(db: Session, family: Family) -> BudgetSummaryOut | None:
    period = current_period(db, family)
    if period is None:
        return None
    overall = next((b for b in period.budgets if b.category is None), None)
    if overall is None:
        return None
    usage = period_usage(db, family, period)
    used = usage.get(None, _ZERO)
    amount = as_money(overall.amount)
    percent_used, state = derive_state(used, amount)
    return BudgetSummaryOut(
        period_id=period.id,
        label_month=period.label_month,
        start_date=period.start_date,
        end_date=period.end_date,
        amount=amount,
        used=used,
        remaining=as_money(amount - used),
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
    seen: set[str | None] = set()
    result: list[BudgetLineIn] = []
    for line in lines:
        if line.category in seen:
            raise bad_request("Duplicate budget category in request")
        seen.add(line.category)
        result.append(line)
    return result


def _replace_period_budgets(db: Session, period: BudgetPeriod, lines: list[BudgetLineIn]) -> None:
    # Flush deletes before inserts — otherwise SQLAlchemy may INSERT the new
    # overall/category rows before DELETE, violating uq_budgets_period_overall.
    for existing in list(period.budgets):
        db.delete(existing)
    db.flush()
    for line in _dedupe_budget_lines(lines):
        db.add(
            Budget(
                period_id=period.id,
                category=line.category,
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
    used = period_usage(db, family, period).get(budget.category, _ZERO)
    out = budget_to_out(budget, family_id=family.id, currency=period.currency, used=used)
    period_out = period_to_out(db, family, get_period(db, period.id))
    _broadcast_period(family.id, period_out)
    return out


def delete_budget(db: Session, budget: Budget) -> None:
    period = get_period(db, budget.period_id)
    family_id = period.family_id
    budget_id = budget.id
    db.delete(budget)
    db.commit()
    hub.broadcast(
        family_id,
        {"type": "budget.deleted", "budget_id": str(budget_id)},
    )
    # Also refresh period view for clients listening to period updates
    family = db.get(Family, family_id)
    if family is not None:
        try:
            refreshed = get_period(db, period.id)
            _broadcast_period(family_id, period_to_out(db, family, refreshed))
        except Exception:  # noqa: BLE001
            pass


def _scope_label(category: str | None) -> str:
    return category if category else "Household"


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
    used: Decimal,
    threshold: int,
    actor_user_id: UUID | None,
    period: BudgetPeriod,
) -> None:
    scope = _scope_label(budget.category)
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
    usage = period_usage(db, family, period)
    for budget in period.budgets:
        used = usage.get(budget.category, _ZERO)
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
    usage = period_usage(db, family, period)
    for budget in period.budgets:
        used = usage.get(budget.category, _ZERO)
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
