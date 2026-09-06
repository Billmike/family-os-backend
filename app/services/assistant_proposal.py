from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import NamedTuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.money import as_money
from app.models.budget import BudgetPeriod
from app.models.budget_subcategory import BudgetSubcategory
from app.models.family import Family, FamilyMember
from app.models.personal_expense import PersonalExpenseAccount
from app.schemas.assistant import ExpenseProposal
from app.services import budget_subcategory as subcategory_service
from app.services import family as family_service
from app.services.budget import current_period

HOUSEHOLD_PHRASES = ("household", "family", "for the house", "shared")
PERSONAL_PHRASES = ("personal", "my money", "my account", "private")
DESTINATION_HOUSEHOLD = "household"
DESTINATION_PERSONAL = "personal"
PERSONAL_UNAVAILABLE = "You don't have a Personal account, so I can't draft a Personal expense."


class AssistantCatalog(NamedTuple):
    subcategories: list[BudgetSubcategory]
    accounts: list[PersonalExpenseAccount]
    members: list[FamilyMember]
    periods: list[BudgetPeriod]
    caller_member_id: UUID | None
    current_period_id: UUID | None


def load_catalog(db: Session, *, family_id: UUID, user_id: UUID) -> AssistantCatalog:
    subcategories = subcategory_service.ensure_family_subcategories(db, family_id)
    accounts = (
        db.query(PersonalExpenseAccount)
        .filter(PersonalExpenseAccount.user_id == user_id)
        .order_by(PersonalExpenseAccount.sort_order.asc(), PersonalExpenseAccount.created_at.asc())
        .all()
    )
    members = family_service.list_members(db, family_id)
    caller = next((row for row in members if row.user_id == user_id), None)
    family = db.get(Family, family_id)
    periods = (
        db.query(BudgetPeriod)
        .filter(BudgetPeriod.family_id == family_id)
        .order_by(BudgetPeriod.start_date.desc())
        .all()
    )
    current = current_period(db, family) if family is not None else None
    return AssistantCatalog(
        subcategories=subcategories,
        accounts=accounts,
        members=members,
        periods=periods,
        caller_member_id=caller.id if caller is not None else None,
        current_period_id=current.id if current is not None else None,
    )


def format_catalog(catalog: AssistantCatalog) -> str:
    lines = ["subcategories:"]
    if catalog.subcategories:
        lines.extend(
            f"- id: {row.id} name: {row.name} group: {row.group}" for row in catalog.subcategories
        )
    else:
        lines.append("- none")
    lines.append("personal_accounts:")
    if catalog.accounts:
        lines.extend(f"- id: {row.id} name: {row.name}" for row in catalog.accounts)
    else:
        lines.append("- none")
    lines.append("members:")
    if catalog.members:
        for row in catalog.members:
            suffix = " caller: true" if row.id == catalog.caller_member_id else ""
            lines.append(f"- id: {row.id} name: {row.name}{suffix}")
    else:
        lines.append("- none")
    lines.append("budget_periods:")
    if catalog.periods:
        for row in catalog.periods:
            suffix = " current: true" if row.id == catalog.current_period_id else ""
            lines.append(f"- id: {row.id} label_month: {row.label_month}{suffix}")
    else:
        lines.append("- none")
    return "\n".join(lines)


def latest_user_text(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content") or ""
    return ""


def _contains_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(phrase in lowered for phrase in phrases)


def _contains_amount(text: str, amount: Decimal) -> bool:
    money = as_money(amount)
    haystack = text.replace(",", ".")
    if money == money.to_integral():
        pattern = rf"(?<!\d){int(money)}(?:\.0+)?(?!\d)"
    else:
        pattern = rf"(?<!\d){money}(?!\d)"
    return re.search(pattern, haystack) is not None


def contains_token(text: str, token: str | None) -> bool:
    if not token:
        return False
    return re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text, re.IGNORECASE) is not None


def _parse_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _parse_amount(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        amount = as_money(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return amount


def _parse_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_text(value: object) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def title_case_merchant(merchant: str | None) -> str | None:
    if merchant is None:
        return None
    return " ".join(_title_case_merchant_token(token) for token in merchant.split())


def _title_case_merchant_token(token: str) -> str:
    letters = [ch for ch in token if ch.isalpha()]
    if not letters:
        return token
    if not (all(ch.islower() for ch in letters) or all(ch.isupper() for ch in letters)):
        return token
    first, *rest = token
    titled_first = first.upper() if first.isalpha() else first
    return titled_first + "".join(ch.lower() if ch.isalpha() else ch for ch in rest)


def destination_from_text(text: str, account_names: list[str]) -> tuple[str | None, bool]:
    named_account = any(contains_token(text, name) for name in account_names)
    if named_account:
        return DESTINATION_PERSONAL, True
    if _contains_phrase(text, HOUSEHOLD_PHRASES):
        return DESTINATION_HOUSEHOLD, True
    if _contains_phrase(text, PERSONAL_PHRASES):
        return DESTINATION_PERSONAL, True
    return None, False


def proposal_from_tool(
    args: dict,
    *,
    user_text: str,
    subcategories: list[BudgetSubcategory],
    accounts: list[PersonalExpenseAccount],
) -> ExpenseProposal:
    subcategory_ids = {row.id: row for row in subcategories}
    account_ids = {row.id: row for row in accounts}
    account_names = [row.name for row in accounts]

    destination_named, destination_explicit = destination_from_text(user_text, account_names)
    raw_destination = args.get("destination")
    if not accounts:
        destination = DESTINATION_HOUSEHOLD
        destination_explicit = destination_named == DESTINATION_HOUSEHOLD
    elif destination_named:
        destination = destination_named
    elif raw_destination in (DESTINATION_HOUSEHOLD, DESTINATION_PERSONAL):
        destination = raw_destination
    else:
        destination = None

    subcategory_id = _parse_uuid(args.get("subcategory_id"))
    if subcategory_id not in subcategory_ids:
        subcategory_id = None
    subcategory_name = subcategory_ids[subcategory_id].name if subcategory_id else None

    account_id = _parse_uuid(args.get("account_id"))
    if account_id not in account_ids:
        account_id = None
    named_account = next((row for row in accounts if contains_token(user_text, row.name)), None)
    if destination == DESTINATION_PERSONAL:
        if named_account:
            account_id = named_account.id
        elif len(accounts) == 1:
            account_id = accounts[0].id
        else:
            account_id = None
    elif destination == DESTINATION_HOUSEHOLD:
        account_id = None
    account_name = account_ids[account_id].name if account_id else None

    amount = _parse_amount(args.get("amount"))
    merchant = title_case_merchant(_parse_text(args.get("merchant")))
    note = _parse_text(args.get("note"))
    category = _parse_text(args.get("category"))
    occurred_on = _parse_date(args.get("occurred_on"))

    return ExpenseProposal(
        destination=destination,
        account_id=account_id,
        amount=amount,
        subcategory_id=subcategory_id,
        category=category,
        merchant=merchant,
        note=note,
        occurred_on=occurred_on,
        destination_explicit=destination_explicit,
        account_id_explicit=bool(account_name and contains_token(user_text, account_name)),
        amount_explicit=bool(amount is not None and _contains_amount(user_text, amount)),
        subcategory_id_explicit=bool(subcategory_name and contains_token(user_text, subcategory_name)),
        category_explicit=bool(category and contains_token(user_text, category)),
        merchant_explicit=bool(merchant and contains_token(user_text, merchant)),
        note_explicit=bool(note and contains_token(user_text, note)),
        occurred_on_explicit=bool(occurred_on and occurred_on.isoformat() in user_text),
    )
