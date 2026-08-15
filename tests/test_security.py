"""Security-focused unit tests for JWT secret validation and push delivery."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AppError
from app.core.config import Settings, validate_jwt_secret
from app.services.notifications import (
    PUSH_TIMEOUT_SECONDS,
    _vapid_sub_claim,
    send_push_to_user,
    validate_push_endpoint,
)


def test_validate_jwt_secret_rejects_known_placeholders() -> None:
    for secret in (
        "dev-secret-change-me",
        "local-dev-secret-change-in-production",
        "change-me-to-a-long-random-secret",
        "short",
    ):
        settings = Settings(jwt_secret=secret, environment="development")
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            validate_jwt_secret(settings)

    empty = Settings.model_construct(jwt_secret="", environment="development")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_jwt_secret(empty)


def test_validate_jwt_secret_allows_strong_secret() -> None:
    settings = Settings(
        jwt_secret="a" * 32,
        environment="development",
    )
    validate_jwt_secret(settings)


def test_validate_jwt_secret_skips_strength_in_test_env() -> None:
    settings = Settings(jwt_secret="test-secret", environment="test")
    validate_jwt_secret(settings)


def test_validate_push_endpoint_allowlist() -> None:
    validate_push_endpoint("https://fcm.googleapis.com/fcm/send/abc")
    validate_push_endpoint("https://updates.push.services.mozilla.com/wpush/v2/x")
    validate_push_endpoint("https://web.push.apple.com/xyz")
    with pytest.raises(AppError):
        validate_push_endpoint("http://fcm.googleapis.com/fcm/send/abc")
    with pytest.raises(AppError):
        validate_push_endpoint("https://127.0.0.1/push")


def test_vapid_sub_claim_normalizes_bare_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_contact_email="user@example.com"),
    )
    assert _vapid_sub_claim() == "mailto:user@example.com"


def test_vapid_sub_claim_keeps_mailto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_contact_email="mailto:user@example.com"),
    )
    assert _vapid_sub_claim() == "mailto:user@example.com"


def test_send_push_passes_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_private_key="priv", vapid_public_key="pub", vapid_contact_email="mailto:t@t"),
    )
    sub = MagicMock()
    sub.id = uuid4()
    sub.endpoint = "https://fcm.googleapis.com/fcm/send/abc"
    sub.p256dh = "p"
    sub.auth = "a"

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [sub]

    with patch("pywebpush.webpush") as webpush_mock:
        send_push_to_user(db, uuid4(), {"title": "t"})
        webpush_mock.assert_called_once()
        assert webpush_mock.call_args.kwargs["timeout"] == PUSH_TIMEOUT_SECONDS
        assert webpush_mock.call_args.kwargs["vapid_claims"] == {"sub": "mailto:t@t"}


def test_send_push_removes_gone_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    from pywebpush import WebPushException

    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_private_key="priv", vapid_public_key="pub", vapid_contact_email="user@x.com"),
    )
    sub = MagicMock()
    sub.id = uuid4()
    sub.endpoint = "https://fcm.googleapis.com/fcm/send/abc"
    sub.p256dh = "p"
    sub.auth = "a"

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [sub]

    response = MagicMock(status_code=410)
    with patch("pywebpush.webpush", side_effect=WebPushException("gone", response=response)):
        send_push_to_user(db, uuid4(), {"title": "t"})
    db.delete.assert_called_once_with(sub)
