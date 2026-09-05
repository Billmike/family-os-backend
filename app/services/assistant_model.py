import json
from typing import Any

from pydantic import BaseModel

from app.core.config import get_settings

DEFAULT_REFUSE = "I can only help you add an expense."

SYSTEM_PROMPT = """You help a family member add one expense. That is your only job.
If the latest user message is not about a spend they already made, refuse in one short sentence.
Do not answer budget questions, shopping lists, email, calendar, or anything else.
You may call propose_expense at most once when they described a spend. Never invent another tool."""

PROPOSE_EXPENSE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "propose_expense",
        "description": "Draft an expense the member can confirm. Do not write the row.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "destination": {
                    "type": ["string", "null"],
                    "enum": ["household", "personal", None],
                },
                "account_id": {"type": ["string", "null"]},
                "amount": {"type": ["number", "null"]},
                "subcategory_id": {"type": ["string", "null"]},
                "category": {"type": ["string", "null"]},
                "merchant": {"type": ["string", "null"]},
                "note": {"type": ["string", "null"]},
                "occurred_on": {"type": ["string", "null"]},
            },
            "required": [
                "destination",
                "account_id",
                "amount",
                "subcategory_id",
                "category",
                "merchant",
                "note",
                "occurred_on",
            ],
        },
    },
}


class AssistantModelResult(BaseModel):
    assistant_text: str
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None


def complete_assistant_turn(*, messages: list[dict[str, str]]) -> AssistantModelResult:
    settings = get_settings()
    from openai import OpenAI

    from app.core.exceptions import service_unavailable

    client = OpenAI(api_key=settings.openai_api_key)
    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
            tools=[PROPOSE_EXPENSE_TOOL],
            tool_choice="auto",
            temperature=0,
        )
    except Exception as exc:
        raise service_unavailable(
            "Ask assistant is unavailable right now.",
            code="assistant_unavailable",
        ) from exc
    if not response.choices:
        return AssistantModelResult(assistant_text=DEFAULT_REFUSE)
    choice = response.choices[0].message
    tool_calls = choice.tool_calls or []
    first = tool_calls[0] if tool_calls else None
    tool_name = first.function.name if first else None
    tool_args: dict[str, Any] | None = None
    if first and tool_name == "propose_expense":
        try:
            parsed = json.loads(first.function.arguments or "{}")
        except json.JSONDecodeError:
            parsed = None
        tool_args = parsed if isinstance(parsed, dict) else None
    else:
        tool_name = None
    text = (choice.content or "").strip() or DEFAULT_REFUSE
    return AssistantModelResult(assistant_text=text, tool_name=tool_name, tool_args=tool_args)
