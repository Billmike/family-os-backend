from datetime import datetime, timezone
import logging
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, not_found
from app.core.money import as_money
from app.core.timeutil import family_now, month_bounds, month_key, parse_year_month
from app.models.budget import Budget, BudgetAlert
from app.models.expense import Expense
from app.models.family import Family
from app.models.user import User, utcnow
from app.realtime.hub import hub
from app.services import notifications as notification_service
from app.schemas.budget import BudgetCreate, BudgetListOut, BudgetOut, BudgetState, BudgetSummaryOut, BudgetUpdate

logger = logging.getLogger(__name__)

THRESHOLD_WARNING = 80
THRESHOLD_OVER = 100
_ZERO = Decimal("0.00")


def month_usage(db: Session, family: Family, month: str) -> dict[str | None, Decimal]:
    """Return {category: total} for the month, plus None key for overall total."""
    try:
        year, month_num = parse_year_month(month)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    start, end = month_bounds(family.timezone, year, month_num)
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


def budget_to_out(
    budget: Budget,
    *,
    month: str,
    used: Decimal,
) -> BudgetOut:
    amount = as_money(budget.amount)
    used_money = as_money(used)
    percent_used, state = derive_state(used_money, amount)
    remaining = as_money(amount - used_money)
    return BudgetOut(
        id=budget.id,
        family_id=budget.family_id,
        category=budget.category,
        amount=amount,
        currency=budget.currency,
        month=month,
        used=used_money,
        remaining=remaining,
        percent_used=percent_used,
        state=state,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


def overall_budget_summary(
    db: Session,
    family: Family,
    *,
    month: str | None = None,
) -> BudgetSummaryOut | None:
    resolved_month = month or month_key(family_now(family.timezone), family.timezone)
    overall = (
        db.query(Budget)
        .filter(Budget.family_id == family.id, Budget.category.is_(None))
        .first()
    )
    if overall is None:
        return None
    usage = month_usage(db, family, resolved_month)
    used = usage.get(None, _ZERO)
    amount = as_money(overall.amount)
    percent_used, state = derive_state(used, amount)
    return BudgetSummaryOut(
        amount=amount,
        used=used,
        remaining=as_money(amount - used),
        percent_used=percent_used,
        state=state,
    )


def list_budgets(db: Session, family: Family, *, month: str | None = None) -> BudgetListOut:
    resolved_month = month or month_key(family_now(family.timezone), family.timezone)
    rows = (
        db.query(Budget)
        .filter(Budget.family_id == family.id)
        .order_by(Budget.category.asc().nullsfirst())
        .all()
    )
    usage = month_usage(db, family, resolved_month)
    overall_out: BudgetOut | None = None
    category_outs: list[BudgetOut] = []
    currency = "EUR"
    for budget in rows:
        used = usage.get(budget.category, _ZERO)
        out = budget_to_out(budget, month=resolved_month, used=used)
        currency = budget.currency or currency
        if budget.category is None:
            overall_out = out
        else:
            category_outs.append(out)
    return BudgetListOut(
        month=resolved_month,
        currency=currency,
        overall=overall_out,
        categories=category_outs,
    )


def get_budget(db: Session, budget_id: UUID) -> Budget:
    budget = db.get(Budget, budget_id)
    if budget is None:
        raise not_found("Budget not found")
    return budget


def _find_budget(db: Session, family_id: UUID, category: str | None) -> Budget | None:
    query = db.query(Budget).filter(Budget.family_id == family_id)
    if category is None:
        return query.filter(Budget.category.is_(None)).first()
    return query.filter(Budget.category == category).first()


def _apply_budget_update(budget: Budget, data: BudgetUpdate) -> None:
    budget.amount = data.amount
    budget.updated_at = utcnow()


def _broadcast_budget(family_id: UUID, event_type: str, budget_out: BudgetOut) -> None:
    hub.broadcast(
        family_id,
        {
            "type": event_type,
            "budget": budget_out.model_dump(mode="json"),
        },
    )


def upsert_budget(db: Session, family: Family, user: User, data: BudgetCreate) -> tuple[BudgetOut, bool]:
    """Create or update a budget. Returns (budget_out, created)."""
    existing = _find_budget(db, family.id, data.category)
    month = month_key(family_now(family.timezone), family.timezone)
    if existing is not None:
        _apply_budget_update(existing, BudgetUpdate(amount=data.amount))
        if data.currency:
            existing.currency = data.currency
        db.commit()
        db.refresh(existing)
        used = month_usage(db, family, month).get(data.category, _ZERO)
        out = budget_to_out(existing, month=month, used=used)
        _broadcast_budget(family.id, "budget.updated", out)
        return out, False

    budget = Budget(
        family_id=family.id,
        category=data.category,
        amount=data.amount,
        currency=data.currency,
        created_by=user.id,
    )
    db.add(budget)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = _find_budget(db, family.id, data.category)
        if raced is None:
            raise
        _apply_budget_update(raced, BudgetUpdate(amount=data.amount))
        if data.currency:
            raced.currency = data.currency
        db.commit()
        db.refresh(raced)
        used = month_usage(db, family, month).get(data.category, _ZERO)
        out = budget_to_out(raced, month=month, used=used)
        _broadcast_budget(family.id, "budget.updated", out)
        return out, False

    db.refresh(budget)
    used = month_usage(db, family, month).get(data.category, _ZERO)
    out = budget_to_out(budget, month=month, used=used)
    _broadcast_budget(family.id, "budget.updated", out)
    return out, True


def update_budget(db: Session, family: Family, budget: Budget, data: BudgetUpdate) -> BudgetOut:
    _apply_budget_update(budget, data)
    db.commit()
    db.refresh(budget)
    month = month_key(family_now(family.timezone), family.timezone)
    used = month_usage(db, family, month).get(budget.category, _ZERO)
    out = budget_to_out(budget, month=month, used=used)
    _broadcast_budget(family.id, "budget.updated", out)
    return out


def delete_budget(db: Session, budget: Budget) -> None:
    budget_id = budget.id
    family_id = budget.family_id
    db.delete(budget)
    db.commit()
    hub.broadcast(
        family_id,
        {"type": "budget.deleted", "budget_id": str(budget_id)},
    )


def _scope_label(category: str | None) -> str:
    return category if category else "Household"


def _alert_exists(db: Session, budget_id: UUID, month: str, threshold: int) -> bool:
    return (
        db.query(BudgetAlert)
        .filter(
            BudgetAlert.budget_id == budget_id,
            BudgetAlert.month == month,
            BudgetAlert.threshold == threshold,
        )
        .first()
        is not None
    )


def _record_alert(db: Session, budget_id: UUID, month: str, threshold: int) -> None:
    if _alert_exists(db, budget_id, month, threshold):
        return
    db.add(
        BudgetAlert(
            budget_id=budget_id,
            month=month,
            threshold=threshold,
            notified_at=datetime.now(timezone.utc),
        )
    )
    db.commit()


def _clear_alerts_below(db: Session, budget_id: UUID, month: str, percent_used: int) -> None:
    thresholds = [t for t in (80, 100) if percent_used < t]
    if not thresholds:
        return
    (
        db.query(BudgetAlert)
        .filter(
            BudgetAlert.budget_id == budget_id,
            BudgetAlert.month == month,
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
        actor_user_id=actor_user_id or budget.created_by,
        pref_field="budget_alerts",
        type="budget",
        title=title,
        body=body,
        entity_type="budget",
        entity_id=budget.id,
        include_actor=True,
        family_timezone=family.timezone,
    )


def recover_budget_alerts(db: Session, family_id: UUID, *, month: str | None = None) -> None:
    family = db.get(Family, family_id)
    if family is None:
        return
    resolved_month = month or month_key(family_now(family.timezone), family.timezone)
    usage = month_usage(db, family, resolved_month)
    budgets = db.query(Budget).filter(Budget.family_id == family_id).all()
    for budget in budgets:
        used = usage.get(budget.category, _ZERO)
        percent_used, _ = derive_state(used, as_money(budget.amount))
        _clear_alerts_below(db, budget.id, resolved_month, percent_used)


def evaluate_budget_alerts(
    db: Session,
    family_id: UUID,
    *,
    month: str | None = None,
    actor_user_id: UUID | None = None,
) -> None:
    family = db.get(Family, family_id)
    if family is None:
        return
    resolved_month = month or month_key(family_now(family.timezone), family.timezone)
    usage = month_usage(db, family, resolved_month)
    budgets = db.query(Budget).filter(Budget.family_id == family_id).all()
    for budget in budgets:
        used = usage.get(budget.category, _ZERO)
        amount = as_money(budget.amount)
        percent_used, _ = derive_state(used, amount)

        notify_threshold: int | None = None
        for threshold in (100, 80):
            if percent_used >= threshold and not _alert_exists(db, budget.id, resolved_month, threshold):
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
        )
        _record_alert(db, budget.id, resolved_month, notify_threshold)
        if notify_threshold == 100 and not _alert_exists(db, budget.id, resolved_month, 80):
            _record_alert(db, budget.id, resolved_month, 80)


def safe_evaluate_budget_alerts(
    db: Session,
    family_id: UUID,
    *,
    actor_user_id: UUID | None = None,
) -> None:
    try:
        evaluate_budget_alerts(db, family_id, actor_user_id=actor_user_id)
    except Exception:  # noqa: BLE001
        logger.exception("Budget alert evaluation failed for family %s", family_id)


def safe_recover_budget_alerts(db: Session, family_id: UUID) -> None:
    try:
        recover_budget_alerts(db, family_id)
    except Exception:  # noqa: BLE001
        logger.exception("Budget alert recovery failed for family %s", family_id)
