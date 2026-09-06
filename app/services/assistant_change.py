from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.core.money import as_money
from app.core.timeutil import family_today
from app.models.family import Family
from app.models.user import User
from app.schemas.assistant import ExpenseChangeProposal, ExpenseList, ExpenseListRow
from app.services import assistant_list
from app.services.assistant_list import WRITABLE_SOURCES, named_month_label
from app.services.assistant_proposal import (
    AssistantCatalog,
    DESTINATION_PERSONAL,
    contains_amount,
    contains_token,
    parse_amount,
    parse_date,
    parse_text,
    parse_uuid,
    title_case_merchant,
)

ASK_WHICH_EXPENSE = "Which expense do you want to change?"
ASK_TAP_ROW = "Tap the row you want to change."
CANNOT_CHANGE_HERE = "That expense can't be changed here."
ASK_CHANGE_WINDOW = "I can change an expense in one month or one budget period. Which do you want?"
HOUSEHOLD_NO_MATCH = "I didn't find a matching expense in the household expenses for {period}."
PERSONAL_NO_MATCH = "I didn't find a matching expense in your {account} expenses for {month}."
_INDEX_FOLLOW_UP = re.compile(
    r"\b(?:the\s+(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th))\s+one|that\s+one|this\s+one)\b",
    re.IGNORECASE,
)
_BARE_DEMONSTRATIVE = re.compile(
    r"^(?:(?:change|delete)\s+)?(?:that|this)\s+\w+[.?]?$",
    re.IGNORECASE,
)
_WEEKDAYS = {name.lower(): index for index, name in enumerate(calendar.day_name)}
_WEEKDAY_RE = re.compile(
    rf"\b({'|'.join(_WEEKDAYS)})\b",
    re.IGNORECASE,
)


class ChangeTurnResult(NamedTuple):
    change_proposal: ExpenseChangeProposal | None
    expense_list: ExpenseList | None
    message: str | None


def change_from_tool(
    db: Session,
    *,
    family: Family,
    user: User,
    catalog: AssistantCatalog,
    user_text: str,
    tool_args: dict,
    destination_hint: str | None,
) -> ChangeTurnResult:
    if _asks_to_tap_row(user_text):
        return ChangeTurnResult(change_proposal=None, expense_list=None, message=ASK_TAP_ROW)
    merchant = title_case_merchant(parse_text(tool_args.get("merchant")))
    amount = parse_amount(tool_args.get("amount"))
    occurred_on = parse_date(tool_args.get("occurred_on"))
    if merchant is None and amount is None and occurred_on is None:
        return ChangeTurnResult(change_proposal=None, expense_list=None, message=ASK_WHICH_EXPENSE)
    search_text = _search_text_for_window(user_text, family, occurred_on)
    listed = assistant_list.list_from_tool(
        db,
        family=family,
        user=user,
        catalog=catalog,
        user_text=search_text,
        tool_args=tool_args,
        destination_hint=destination_hint,
    )
    if listed.message == assistant_list.ASK_ONE_PERIOD:
        return ChangeTurnResult(change_proposal=None, expense_list=None, message=ASK_CHANGE_WINDOW)
    if listed.message:
        return ChangeTurnResult(change_proposal=None, expense_list=None, message=listed.message)
    expense_list = listed.expense_list
    if expense_list is None:
        return ChangeTurnResult(change_proposal=None, expense_list=None, message=ASK_WHICH_EXPENSE)
    weekday = _weekday_date(user_text, family)
    named_window = _named_a_window(search_text, family, catalog)
    if weekday is not None:
        start, end = _window_dates(catalog, expense_list)
        if start is not None and end is not None and not (start <= weekday <= end):
            if not named_window:
                return ChangeTurnResult(
                    change_proposal=None, expense_list=None, message=ASK_CHANGE_WINDOW
                )
        elif occurred_on is None:
            occurred_on = weekday
    matches = [
        row
        for row in expense_list.rows
        if _row_matches(row, merchant=merchant, amount=amount, occurred_on=occurred_on)
    ]
    if not matches:
        return ChangeTurnResult(
            change_proposal=None,
            expense_list=None,
            message=_no_match_message(expense_list),
        )
    if len(matches) > 1:
        total = as_money(sum((row.amount for row in matches), Decimal("0.00")))
        return ChangeTurnResult(
            change_proposal=None,
            expense_list=expense_list.model_copy(update={"rows": matches, "count": len(matches), "total": total}),
            message=None,
        )
    row = matches[0]
    if row.source_type not in WRITABLE_SOURCES:
        return ChangeTurnResult(change_proposal=None, expense_list=None, message=CANNOT_CHANGE_HERE)
    return ChangeTurnResult(
        change_proposal=_proposal_from_match(
            expense_list,
            row,
            user_text=user_text,
            catalog=catalog,
            tool_args=tool_args,
        ),
        expense_list=None,
        message=None,
    )


def _asks_to_tap_row(user_text: str) -> bool:
    if _INDEX_FOLLOW_UP.search(user_text):
        return True
    return _BARE_DEMONSTRATIVE.fullmatch(user_text.strip()) is not None


def _search_text_for_window(user_text: str, family: Family, occurred_on: date | None) -> str:
    search_text = user_text
    label = named_month_label(user_text, family)
    if label and label not in search_text:
        search_text = f"{search_text} {label}"
    if occurred_on is not None:
        iso_month = f"{occurred_on.year:04d}-{occurred_on.month:02d}"
        if iso_month not in search_text:
            search_text = f"{search_text} {iso_month}"
    return search_text


def _named_a_window(user_text: str, family: Family, catalog: AssistantCatalog) -> bool:
    if named_month_label(user_text, family):
        return True
    return any(row.label_month in user_text for row in catalog.periods)


def _row_matches(
    row: ExpenseListRow,
    *,
    merchant: str | None,
    amount: Decimal | None,
    occurred_on: date | None,
) -> bool:
    if merchant and (not row.merchant or merchant.casefold() not in row.merchant.casefold()):
        return False
    if amount is not None and row.amount != amount:
        return False
    if occurred_on is not None and row.occurred_on != occurred_on:
        return False
    return True


def _no_match_message(expense_list: ExpenseList) -> str:
    if expense_list.destination == DESTINATION_PERSONAL:
        return PERSONAL_NO_MATCH.format(account=expense_list.account_name, month=expense_list.month)
    return HOUSEHOLD_NO_MATCH.format(period=expense_list.period_label)


def _weekday_date(user_text: str, family: Family) -> date | None:
    match = _WEEKDAY_RE.search(user_text)
    if match is None:
        return None
    today = family_today(family.timezone)
    target = _WEEKDAYS[match.group(1).lower()]
    return today - timedelta(days=(today.weekday() - target) % 7)


def _window_dates(
    catalog: AssistantCatalog,
    expense_list: ExpenseList,
) -> tuple[date | None, date | None]:
    if expense_list.destination == DESTINATION_PERSONAL and expense_list.month:
        year, month = (int(part) for part in expense_list.month.split("-"))
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)
    period = next((row for row in catalog.periods if row.id == expense_list.period_id), None)
    if period is None:
        return None, None
    return period.start_date, period.end_date


def _proposal_from_match(
    expense_list: ExpenseList,
    row: ExpenseListRow,
    *,
    user_text: str,
    catalog: AssistantCatalog,
    tool_args: dict,
) -> ExpenseChangeProposal:
    is_personal = expense_list.destination == DESTINATION_PERSONAL
    patch_amount = parse_amount(tool_args.get("patch_amount"))
    patch_merchant = title_case_merchant(parse_text(tool_args.get("patch_merchant")))
    patch_note = parse_text(tool_args.get("patch_note"))
    patch_occurred_on = parse_date(tool_args.get("patch_occurred_on"))
    patch_category = parse_text(tool_args.get("patch_category")) if is_personal else None
    patch_subcategory_id = parse_uuid(tool_args.get("patch_subcategory_id"))
    allowed_subcategories = {item.id: item for item in catalog.subcategories}
    if patch_subcategory_id not in allowed_subcategories:
        patch_subcategory_id = None
    amount = patch_amount if patch_amount is not None else row.amount
    merchant = patch_merchant if patch_merchant is not None else row.merchant
    note = patch_note if patch_note is not None else row.note
    occurred_on = patch_occurred_on if patch_occurred_on is not None else row.occurred_on
    subcategory_id = row.subcategory_id if not is_personal else None
    if patch_subcategory_id is not None and not is_personal:
        subcategory_id = patch_subcategory_id
    category = row.category_or_subcategory_label if is_personal else None
    if patch_category is not None:
        category = patch_category
    subcategory_name = (
        allowed_subcategories[subcategory_id].name if subcategory_id in allowed_subcategories else None
    )
    return ExpenseChangeProposal(
        expense_id=row.id,
        destination=expense_list.destination,
        account_id=expense_list.account_id if is_personal else None,
        amount=amount,
        subcategory_id=subcategory_id,
        category=category,
        merchant=merchant,
        note=note,
        occurred_on=occurred_on,
        amount_explicit=bool(patch_amount is not None and contains_amount(user_text, patch_amount)),
        subcategory_id_explicit=bool(
            patch_subcategory_id is not None and subcategory_name and contains_token(user_text, subcategory_name)
        ),
        category_explicit=bool(patch_category is not None and contains_token(user_text, patch_category)),
        merchant_explicit=bool(patch_merchant is not None and contains_token(user_text, patch_merchant)),
        note_explicit=bool(patch_note is not None and contains_token(user_text, patch_note)),
        occurred_on_explicit=bool(patch_occurred_on is not None and patch_occurred_on.isoformat() in user_text),
        destination_explicit=False,
        account_id_explicit=False,
        writable=True,
    )
