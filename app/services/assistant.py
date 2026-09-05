from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.config import get_settings
from app.core.exceptions import service_unavailable, too_many_requests
from app.schemas.assistant import AssistantMessageIn, AssistantTurnOut
from app.services import assistant_model

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


def run_turn(*, user_id: UUID, messages: list[AssistantMessageIn]) -> AssistantTurnOut:
    require_assistant_available()
    _record_turn(user_id, datetime.now(timezone.utc))
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
    result = assistant_model.complete_assistant_turn(messages=kept)
    return AssistantTurnOut(assistant_text=result.assistant_text, proposal=None)
