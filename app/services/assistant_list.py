from __future__ import annotations

import calendar
import re
from decimal import Decimal
from typing import NamedTuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.money import as_money
from app.core.timeutil import ensure_aware, family_now, family_zone, month_bounds, parse_year_month
from app.models.budget import BudgetPeriod
from app.models.budget_group import is_outflow_group
from app.models.expense import SOURCE_ASSISTANT, SOURCE_MANUAL
from app.models.family import Family
from app.models.personal_expense import PersonalExpense, PersonalExpenseAccount
from app.models.user import User
from app.schemas.assistant import ExpenseList, ExpenseListRow
from app.schemas.expense import ExpenseOut
from app.services.assistant_proposal import (
    AssistantCatalog,
    DESTINATION_HOUSEHOLD,
    DESTINATION_PERSONAL,
    PERSONAL_UNAVAILABLE,
    contains_token,
    destination_from_text,
)
from app.services import expense as expense_service

WRITABLE_SOURCES = frozenset({SOURCE_MANUAL, SOURCE_ASSISTANT})
BUDGET_NOT_SETUP = "Budget is not set up, so I can't show household expenses."
ASK_ONE_PERIOD = "I can show expenses for one month or one budget period. Which do you want?"
HOUSEHOLD_LIST_TEMPLATE = "Here are the household expenses for {period}."
HOUSEHOLD_EMPTY_TEMPLATE = "I didn't find any household expenses in that window."
PERSONAL_LIST_TEMPLATE = "Here are your {account} expenses for {month}."
PERSONAL_EMPTY_TEMPLATE = "I didn't find any {account} expenses in that window."
ASK_DESTINATION = "Do you want household or personal expenses?"
ASK_WHICH_ACCOUNT = "Which Personal account should I show?"

_RANGE_THROUGH = re.compile(r"\b(?:through|thru)\b")
_RANGE_FROM_TO = re.compile(r"\bfrom\b.+\bto\b")
_NAMED_YEAR_MONTH = re.compile(r"\b(\d{4}-(?:0[1-9]|1[0-2]))\b")
_NAMED_YEAR = re.compile(r"\b(20\d{2})\b")
_MONTH_INDEX = {name.lower(): index for index, name in enumerate(calendar.month_name) if name}
_MONTH_NAME = "|".join(re.escape(name) for name in _MONTH_INDEX)
_NAMED_MONTH = re.compile(
    rf"\b(?:for|in|during)\s+({_MONTH_NAME})\b|\b({_MONTH_NAME})\s+(20\d{{2}})\b",
    re.IGNORECASE,
)


class ListTurnResult(NamedTuple):
    expense_list: ExpenseList | None
    message: str | None


def household_list_text(expense_list: ExpenseList) -> str:
    if expense_list.count == 0:
        return HOUSEHOLD_EMPTY_TEMPLATE
    return HOUSEHOLD_LIST_TEMPLATE.format(period=expense_list.period_label)


def personal_list_text(expense_list: ExpenseList) -> str:
    if expense_list.count == 0:
        return PERSONAL_EMPTY_TEMPLATE.format(account=expense_list.account_name)
    return PERSONAL_LIST_TEMPLATE.format(account=expense_list.account_name, month=expense_list.month)


def list_text(expense_list: ExpenseList) -> str:
    if expense_list.destination == DESTINATION_PERSONAL:
        return personal_list_text(expense_list)
    return household_list_text(expense_list)


def list_from_tool(
    db: Session,
    *,
    family: Family,
    user: User,
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
    if _window_is_unmappable(user_text):
        return ListTurnResult(expense_list=None, message=ASK_ONE_PERIOD)
    if destination == DESTINATION_PERSONAL:
        return _personal_list_from_tool(
            db,
            family=family,
            user=user,
            catalog=catalog,
            user_text=user_text,
        )
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


def _personal_list_from_tool(
    db: Session,
    *,
    family: Family,
    user: User,
    catalog: AssistantCatalog,
    user_text: str,
) -> ListTurnResult:
    if not catalog.accounts:
        return ListTurnResult(expense_list=None, message=PERSONAL_UNAVAILABLE)
    account = _resolve_personal_account(catalog.accounts, user_text)
    if account is None:
        return ListTurnResult(expense_list=None, message=ASK_WHICH_ACCOUNT)
    if account.user_id != user.id:
        return ListTurnResult(expense_list=None, message=ASK_WHICH_ACCOUNT)
    month = _resolve_personal_month(user_text, family)
    year, month_num = parse_year_month(month)
    start, end = month_bounds(family.timezone, year, month_num)
    listed = (
        db.query(PersonalExpense)
        .filter(
            PersonalExpense.account_id == account.id,
            PersonalExpense.occurred_at >= start,
            PersonalExpense.occurred_at < end,
        )
        .order_by(PersonalExpense.occurred_at.desc(), PersonalExpense.created_at.desc())
        .all()
    )
    rows = [_personal_to_list_row(row, family_timezone=family.timezone) for row in listed]
    total = as_money(sum((row.amount for row in rows), Decimal("0.00")))
    return ListTurnResult(
        expense_list=ExpenseList(
            destination=DESTINATION_PERSONAL,
            account_id=account.id,
            account_name=account.name,
            month=month,
            period_id=None,
            period_label=None,
            count=len(rows),
            total=total,
            currency=account.currency,
            rows=rows,
        ),
        message=None,
    )


def _resolve_personal_account(
    accounts: list[PersonalExpenseAccount],
    user_text: str,
) -> PersonalExpenseAccount | None:
    named = next((row for row in accounts if contains_token(user_text, row.name)), None)
    if named is not None:
        return named
    if len(accounts) == 1:
        return accounts[0]
    return None


def _resolve_personal_month(user_text: str, family: Family) -> str:
    named = _NAMED_YEAR_MONTH.search(user_text)
    if named is not None:
        return named.group(1)
    now = family_now(family.timezone)
    match = _NAMED_MONTH.search(user_text)
    if match is None:
        return f"{now.year:04d}-{now.month:02d}"
    month_name = (match.group(1) or match.group(2)).casefold()
    month_num = _MONTH_INDEX[month_name]
    year = now.year
    if match.group(3):
        year = int(match.group(3))
    else:
        year_match = _NAMED_YEAR.search(user_text)
        if year_match is not None:
            year = int(year_match.group(1))
    return f"{year:04d}-{month_num:02d}"


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


def _personal_to_list_row(row: PersonalExpense, *, family_timezone: str) -> ExpenseListRow:
    occurred_on = ensure_aware(row.occurred_at).astimezone(family_zone(family_timezone)).date()
    return ExpenseListRow(
        id=row.id,
        occurred_on=occurred_on,
        merchant=row.merchant,
        amount=as_money(row.amount),
        category_or_subcategory_label=row.category,
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
