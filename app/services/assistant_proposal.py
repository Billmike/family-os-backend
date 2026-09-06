from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.money import as_money
from app.models.budget_subcategory import BudgetSubcategory
from app.models.personal_expense import PersonalExpenseAccount
from app.schemas.assistant import ExpenseProposal
from app.services import budget_subcategory as subcategory_service

HOUSEHOLD_PHRASES = ("household", "family", "for the house", "shared")
PERSONAL_PHRASES = ("personal", "my money", "my account", "private")
DESTINATION_HOUSEHOLD = "household"
DESTINATION_PERSONAL = "personal"
PERSONAL_UNAVAILABLE = "You don't have a Personal account, so I can't draft a Personal expense."


def load_catalog(db: Session, *, family_id: UUID, user_id: UUID) -> tuple[list[BudgetSubcategory], list[PersonalExpenseAccount]]:
    subcategories = subcategory_service.ensure_family_subcategories(db, family_id)
    accounts = (
        db.query(PersonalExpenseAccount)
        .filter(PersonalExpenseAccount.user_id == user_id)
        .order_by(PersonalExpenseAccount.sort_order.asc(), PersonalExpenseAccount.created_at.asc())
        .all()
    )
    return subcategories, accounts


def format_catalog(subcategories: list[BudgetSubcategory], accounts: list[PersonalExpenseAccount]) -> str:
    lines = ["subcategories:"]
    if subcategories:
        lines.extend(f"- id: {row.id} name: {row.name} group: {row.group}" for row in subcategories)
    else:
        lines.append("- none")
    lines.append("personal_accounts:")
    if accounts:
        lines.extend(f"- id: {row.id} name: {row.name}" for row in accounts)
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


def _contains_token(text: str, token: str | None) -> bool:
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
    named_account = any(_contains_token(text, name) for name in account_names)
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
    named_account = next((row for row in accounts if _contains_token(user_text, row.name)), None)
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
        account_id_explicit=bool(account_name and _contains_token(user_text, account_name)),
        amount_explicit=bool(amount is not None and _contains_amount(user_text, amount)),
        subcategory_id_explicit=bool(subcategory_name and _contains_token(user_text, subcategory_name)),
        category_explicit=bool(category and _contains_token(user_text, category)),
        merchant_explicit=bool(merchant and _contains_token(user_text, merchant)),
        note_explicit=bool(note and _contains_token(user_text, note)),
        occurred_on_explicit=bool(occurred_on and occurred_on.isoformat() in user_text),
    )
