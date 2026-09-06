from __future__ import annotations

import re
from decimal import Decimal
from typing import NamedTuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.money import as_money
from app.core.timeutil import ensure_aware, family_zone
from app.models.budget import BudgetPeriod
from app.models.budget_group import is_outflow_group
from app.models.expense import SOURCE_ASSISTANT, SOURCE_MANUAL
from app.models.family import Family
from app.schemas.assistant import ExpenseList, ExpenseListRow
from app.schemas.expense import ExpenseOut
from app.services.assistant_proposal import (
    AssistantCatalog,
    DESTINATION_HOUSEHOLD,
    DESTINATION_PERSONAL,
    destination_from_text,
)
from app.services import expense as expense_service

WRITABLE_SOURCES = frozenset({SOURCE_MANUAL, SOURCE_ASSISTANT})
BUDGET_NOT_SETUP = "Budget is not set up, so I can't show household expenses."
ASK_ONE_PERIOD = "I can show expenses for one month or one budget period. Which do you want?"
HOUSEHOLD_LIST_TEMPLATE = "Here are the household expenses for {period}."
HOUSEHOLD_EMPTY_TEMPLATE = "I didn't find any household expenses in that window."
ASK_DESTINATION = "Do you want household or personal expenses?"

_RANGE_THROUGH = re.compile(r"\b(?:through|thru)\b")
_RANGE_FROM_TO = re.compile(r"\bfrom\b.+\bto\b")


class ListTurnResult(NamedTuple):
    expense_list: ExpenseList | None
    message: str | None


def household_list_text(expense_list: ExpenseList) -> str:
    if expense_list.count == 0:
        return HOUSEHOLD_EMPTY_TEMPLATE
    return HOUSEHOLD_LIST_TEMPLATE.format(period=expense_list.period_label)


def family_list_from_tool(
    db: Session,
    *,
    family: Family,
    catalog: AssistantCatalog,
    user_text: str,
    tool_args: dict,
    destination_hint: str | None,
) -> ListTurnResult:
    destination = _resolve_list_destination(
        user_text,
        [row.name for row in catalog.accounts],
        destination_hint,
    )
    if destination is None:
        return ListTurnResult(expense_list=None, message=ASK_DESTINATION)
    if destination != DESTINATION_HOUSEHOLD:
        return ListTurnResult(expense_list=None, message=None)
    if _window_is_unmappable(user_text):
        return ListTurnResult(expense_list=None, message=ASK_ONE_PERIOD)
    period = _resolve_household_period(catalog, user_text, tool_args)
    if period is None:
        return ListTurnResult(expense_list=None, message=BUDGET_NOT_SETUP)
    listed = expense_service.list_expenses(db, family, period_id=period.id)
    rows = [_to_list_row(row, family_timezone=family.timezone) for row in listed if is_outflow_group(row.group)]
    total = as_money(sum((row.amount for row in rows), Decimal("0.00")))
    return ListTurnResult(
        expense_list=ExpenseList(
            destination=DESTINATION_HOUSEHOLD,
            account_id=None,
            account_name=None,
            month=None,
            period_id=period.id,
            period_label=period.label_month,
            count=len(rows),
            total=total,
            currency=period.currency,
            rows=rows,
        ),
        message=None,
    )


def _resolve_list_destination(
    user_text: str,
    account_names: list[str],
    destination_hint: str | None,
) -> str | None:
    named, _ = destination_from_text(user_text, account_names)
    if named:
        return named
    if destination_hint in (DESTINATION_HOUSEHOLD, DESTINATION_PERSONAL):
        return destination_hint
    if not account_names:
        return DESTINATION_HOUSEHOLD
    return None


def _window_is_unmappable(user_text: str) -> bool:
    lowered = user_text.casefold()
    if "last week" in lowered:
        return True
    if _RANGE_THROUGH.search(lowered):
        return True
    return _RANGE_FROM_TO.search(lowered) is not None


def _resolve_household_period(
    catalog: AssistantCatalog,
    user_text: str,
    tool_args: dict,
) -> BudgetPeriod | None:
    named = next((row for row in catalog.periods if row.label_month in user_text), None)
    if named is not None:
        return named
    allowed = {row.id: row for row in catalog.periods}
    tool_period_id = _parse_uuid(tool_args.get("period_id"))
    if tool_period_id in allowed:
        return allowed[tool_period_id]
    if catalog.current_period_id is None:
        return None
    return allowed.get(catalog.current_period_id)


def _to_list_row(row: ExpenseOut, *, family_timezone: str) -> ExpenseListRow:
    occurred_on = ensure_aware(row.occurred_at).astimezone(family_zone(family_timezone)).date()
    return ExpenseListRow(
        id=row.id,
        occurred_on=occurred_on,
        merchant=row.merchant,
        amount=row.amount,
        category_or_subcategory_label=row.subcategory_name,
        source_type=row.source_type,
        writable=row.source_type in WRITABLE_SOURCES,
    )


def _parse_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None
