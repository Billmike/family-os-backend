"""OpenAI model default and request shape for gpt-5.6-luna."""

from __future__ import annotations

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings, get_settings


def test_openai_model_defaults_to_gpt_5_6_luna(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    settings = Settings(jwt_secret="a" * 32, environment="development", _env_file=None)
    assert settings.openai_model == "gpt-5.6-luna"


def _fake_chat_response(*, content: str, tool_calls: Any | None = None) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls
    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.fixture()
def openai_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_assistant_turn_sends_luna_without_temperature(
    openai_env: None,
) -> None:
    from app.services.assistant_model import complete_assistant_turn

    client = MagicMock()
    client.chat.completions.create.return_value = _fake_chat_response(
        content="I can only help you add an expense.",
    )
    with patch("openai.OpenAI", return_value=client):
        complete_assistant_turn(messages=[{"role": "user", "content": "hi"}])

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-5.6-luna"
    assert "temperature" not in kwargs


def test_receipt_extraction_sends_luna_without_temperature(
    openai_env: None,
) -> None:
    from app.services.receipt_extraction import extract_receipt

    payload = {
        "merchant": "REWE",
        "purchased_at": None,
        "currency": "EUR",
        "subtotal": None,
        "tax_total": None,
        "total": 10.0,
        "suggested_category": "Shopping",
        "items": [],
    }
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_chat_response(
        content=json.dumps(payload),
    )
    with patch("openai.OpenAI", return_value=client):
        extracted = extract_receipt(image_bytes=b"fake-bytes", mime_type="image/jpeg")

    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-5.6-luna"
    assert "temperature" not in kwargs
    assert extracted.model_name == "gpt-5.6-luna"
