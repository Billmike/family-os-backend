from __future__ import annotations

import re
from typing import NamedTuple

from app.models.family import FamilyMember
from app.schemas.assistant import TaskDue, TaskPriority, TaskProposal
from app.services.assistant_proposal import AssistantCatalog, contains_token

ASK_TITLE = "What needs doing?"
ASK_ASSIGNEE = "Who should I assign this to?"
ASK_DUE = "Is this due today or tomorrow?"
DEFAULT_CATEGORY = "Household"
DEFAULT_PRIORITY: TaskPriority = "medium"
DEFAULT_DUE: TaskDue = "today"
TASK_CATEGORIES = ("Household", "Child", "Shopping", "Personal", "Admin", "Other")
TASK_PRIORITIES: tuple[TaskPriority, ...] = ("high", "low", "medium")
MAX_TITLE = 200
RECURRING_PHRASES = ("every week", "weekly", "recurring")
_ASSIGN_TO = re.compile(r"assign(?:ed)?\s+to\s+(.+)", re.IGNORECASE)
_SELF_ASSIGN = re.compile(r"\bme\b", re.IGNORECASE)
_UNMAPPABLE_DUE = re.compile(
    r"\b(?:due|on|by|this|for)\s+"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|\bnext\s+(?:week|month)\b",
    re.IGNORECASE,
)


class TaskTurnResult(NamedTuple):
    task_proposal: TaskProposal | None
    message: str | None


def task_from_tool(
    args: dict,
    *,
    user_text: str,
    catalog: AssistantCatalog,
) -> TaskTurnResult:
    title = _stripped_title(args.get("title"))
    if not title:
        return TaskTurnResult(task_proposal=None, message=ASK_TITLE)
    if _unknown_assignee_named(user_text, catalog.members):
        return TaskTurnResult(task_proposal=None, message=ASK_ASSIGNEE)
    if _due_is_unmappable(user_text):
        return TaskTurnResult(task_proposal=None, message=ASK_DUE)

    named_member = next(
        (row for row in catalog.members if contains_token(user_text, row.name)),
        None,
    )
    assignee_id = named_member.id if named_member is not None else catalog.caller_member_id

    due, due_explicit = _due_from_text(user_text)
    priority, priority_explicit = _priority_from_text(user_text)
    category, category_explicit = _category_from_text(user_text)
    recurring = any(contains_token(user_text, phrase) for phrase in RECURRING_PHRASES)

    return TaskTurnResult(
        task_proposal=TaskProposal(
            title=title,
            assignee_id=assignee_id,
            due=due,
            priority=priority,
            category=category,
            recurring=recurring,
            title_explicit=contains_token(user_text, title),
            assignee_id_explicit=named_member is not None,
            due_explicit=due_explicit,
            priority_explicit=priority_explicit,
            category_explicit=category_explicit,
            recurring_explicit=recurring,
        ),
        message=None,
    )


def _stripped_title(value: object) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    if len(stripped) > MAX_TITLE:
        return stripped[:MAX_TITLE].rstrip()
    return stripped


def _unknown_assignee_named(user_text: str, members: list[FamilyMember]) -> bool:
    match = _ASSIGN_TO.search(user_text)
    if match is None:
        return False
    remainder = match.group(1).split(",")[0].strip()
    if not remainder:
        return False
    if _SELF_ASSIGN.search(remainder):
        return False
    return not any(contains_token(remainder, row.name) for row in members)


def _due_is_unmappable(user_text: str) -> bool:
    if contains_token(user_text, "today") or contains_token(user_text, "tomorrow"):
        return False
    return _UNMAPPABLE_DUE.search(user_text) is not None


def _due_from_text(user_text: str) -> tuple[TaskDue, bool]:
    if contains_token(user_text, "tomorrow"):
        return "tomorrow", True
    if contains_token(user_text, "today"):
        return "today", True
    return DEFAULT_DUE, False


def _priority_from_text(user_text: str) -> tuple[TaskPriority, bool]:
    for priority in TASK_PRIORITIES:
        if contains_token(user_text, priority):
            return priority, True
    return DEFAULT_PRIORITY, False


def _category_from_text(user_text: str) -> tuple[str, bool]:
    for category in TASK_CATEGORIES:
        if contains_token(user_text, category):
            return category, True
    return DEFAULT_CATEGORY, False
