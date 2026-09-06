from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import service_unavailable, too_many_requests
from app.models.family import Family
from app.models.user import User
from app.schemas.assistant import (
    AssistantDestination,
    AssistantMessageIn,
    AssistantTurnOut,
    ExpenseChangeProposal,
    ExpenseList,
    ExpenseProposal,
    TaskProposal,
)
from app.services import assistant_change
from app.services import assistant_list
from app.services import assistant_model
from app.services import assistant_proposal
from app.services import assistant_task

ALLOWED_ROLES = frozenset({"user", "assistant"})
TURNS_PER_HOUR = 30
_HOUR = timedelta(hours=1)
_turn_times: dict[UUID, deque[datetime]] = defaultdict(deque)


def is_assistant_available() -> bool:
    settings = get_settings()
    return bool(settings.assistant_enabled and settings.openai_api_key)


def require_assistant_available() -> None:
    if not is_assistant_available():
        raise service_unavailable(
            "Ask assistant is not configured. Set OPENAI_API_KEY to enable it.",
            code="assistant_unavailable",
        )


def clear_turn_windows() -> None:
    _turn_times.clear()


def _record_turn(user_id: UUID, now: datetime) -> None:
    window = _turn_times[user_id]
    cutoff = now - _HOUR
    while window and window[0] <= cutoff:
        window.popleft()
    if len(window) >= TURNS_PER_HOUR:
        raise too_many_requests(
            "Too many Assistant turns. Try again in an hour.",
            code="assistant_rate_limited",
        )
    window.append(now)


def run_turn(
    *,
    db: Session,
    family_id: UUID,
    user: User,
    messages: list[AssistantMessageIn],
    destination_hint: AssistantDestination | None = None,
) -> AssistantTurnOut:
    # destination_hint is for list and change; add-expense ignores it.
    require_assistant_available()
    _record_turn(user.id, datetime.now(timezone.utc))
    kept = [
        {"role": message.role, "content": message.content}
        for message in messages
        if message.role in ALLOWED_ROLES
    ]
    if not kept:
        return AssistantTurnOut(
            assistant_text=assistant_model.DEFAULT_REFUSE,
            proposal=None,
        )
    catalog_data = assistant_proposal.load_catalog(db, family_id=family_id, user_id=user.id)
    user_text = assistant_proposal.latest_user_text(kept)
    destination_named, _ = assistant_proposal.destination_from_text(
        user_text, [row.name for row in catalog_data.accounts]
    )
    catalog = assistant_proposal.format_catalog(catalog_data)
    result = assistant_model.complete_assistant_turn(messages=kept, catalog=catalog)
    if (
        result.tool_name == "propose_expense"
        and destination_named == assistant_proposal.DESTINATION_PERSONAL
        and not catalog_data.accounts
    ):
        return AssistantTurnOut(
            assistant_text=assistant_proposal.PERSONAL_UNAVAILABLE,
            proposal=None,
        )
    proposal = None
    expense_list = None
    list_message = None
    task_proposal = None
    task_message = None
    change_proposal = None
    change_message = None
    family = db.get(Family, family_id)
    if result.tool_name == "propose_expense" and result.tool_args is not None:
        proposal = assistant_proposal.proposal_from_tool(
            result.tool_args,
            user_text=user_text,
            subcategories=catalog_data.subcategories,
            accounts=catalog_data.accounts,
        )
    elif result.tool_name == "list_expenses" and result.tool_args is not None:
        if family is not None:
            listed = assistant_list.list_from_tool(
                db,
                family=family,
                user=user,
                catalog=catalog_data,
                user_text=user_text,
                tool_args=result.tool_args,
                destination_hint=destination_hint,
            )
            expense_list = listed.expense_list
            list_message = listed.message
    elif result.tool_name == "propose_task" and result.tool_args is not None:
        drafted = assistant_task.task_from_tool(
            result.tool_args,
            user_text=user_text,
            catalog=catalog_data,
        )
        task_proposal = drafted.task_proposal
        task_message = drafted.message
    elif result.tool_name == "propose_expense_change" and result.tool_args is not None:
        if family is not None:
            changed = assistant_change.change_from_tool(
                db,
                family=family,
                user=user,
                catalog=catalog_data,
                user_text=user_text,
                tool_args=result.tool_args,
                destination_hint=destination_hint,
            )
            change_proposal = changed.change_proposal
            expense_list = changed.expense_list
            change_message = changed.message
    return AssistantTurnOut(
        assistant_text=_resolve_assistant_text(
            result.assistant_text,
            proposal,
            expense_list,
            list_message,
            task_proposal,
            task_message,
            change_proposal,
            change_message,
        ),
        proposal=proposal,
        task_proposal=task_proposal,
        expense_list=expense_list,
        change_proposal=change_proposal,
    )


def _resolve_assistant_text(
    model_text: str,
    proposal: ExpenseProposal | None,
    expense_list: ExpenseList | None = None,
    list_message: str | None = None,
    task_proposal: TaskProposal | None = None,
    task_message: str | None = None,
    change_proposal: ExpenseChangeProposal | None = None,
    change_message: str | None = None,
) -> str:
    if list_message:
        return list_message
    if task_message:
        return task_message
    if change_message:
        return change_message
    text = (model_text or "").strip()
    if expense_list is not None:
        return assistant_list.list_text(expense_list)
    if task_proposal is not None:
        if text and text != assistant_model.DEFAULT_REFUSE:
            return text
        return assistant_model.DRAFT_TASK
    if change_proposal is not None:
        if text and text != assistant_model.DEFAULT_REFUSE:
            return text
        return assistant_model.DRAFT_CHANGE
    if proposal is None:
        return text or assistant_model.DEFAULT_REFUSE
    if text and text != assistant_model.DEFAULT_REFUSE:
        return text
    return assistant_model.draft_confirmation(proposal.merchant)
