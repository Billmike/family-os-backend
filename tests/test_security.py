"""Security-focused unit tests for JWT secret validation and push delivery."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import AppError
from app.core.config import Settings, validate_jwt_secret
from app.services.notifications import PUSH_TIMEOUT_SECONDS, send_push_to_user, validate_push_endpoint


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
