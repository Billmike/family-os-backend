"""Security-focused unit tests for JWT secret validation and push delivery."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid

from app.core.exceptions import AppError
from app.core.config import Settings, validate_jwt_secret
from app.models.notification import NotificationPreference, PushSubscription
from app.models.user import User
from app.schemas.notification import PushSubscribeRequest
from app.services.notifications import (
    MAX_PUSH_FAILURES,
    MAX_PUSH_SUBSCRIPTIONS_PER_USER,
    PUSH_BUDGET_SECONDS,
    PUSH_TIMEOUT_SECONDS,
    _rewrap_pem,
    _validated_vapid_private_key,
    _vapid_private_key,
    _vapid_sub_claim,
    is_in_quiet_hours,
    send_push_to_user,
    subscribe_push,
    validate_push_endpoint,
)

# Deterministic test key (not used outside unit tests).
VALID_VAPID_PEM = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg6V+s/SBSPbr7BFoM
YzHL9q0Ze/B5tQ6u6rfMuc4yVJqhRANCAARg5gyhIHJtuOZ2EM5/f3hnZncQrlRV
9KYltk6X10g9IH42l6gu63SNm+1lmqZn1EaqRFZ+7BFL0QROeczcMcVE
-----END PRIVATE KEY-----
"""
VALID_VAPID_PUBLIC = "BGDmDKEgcm245nYQzn9_eGdmdxCuVFX0piW2TpfXSD0gfjaXqC7rdI2b7WWapmfURqpEVn7sEUvRBE55zNwxxUQ"


def _raw_from_pem(pem: str) -> str:
    import base64

    priv = serialization.load_pem_private_key(pem.encode(), password=None)
    raw = priv.private_numbers().private_value.to_bytes(32, "big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


VALID_VAPID_RAW = _raw_from_pem(VALID_VAPID_PEM)


def _vapid_settings() -> MagicMock:
    return MagicMock(
        vapid_private_key=VALID_VAPID_PEM,
        vapid_public_key=VALID_VAPID_PUBLIC,
        vapid_contact_email="mailto:t@t",
    )


def _mock_sub(endpoint: str = "https://fcm.googleapis.com/fcm/send/abc") -> MagicMock:
    sub = MagicMock()
    sub.id = uuid4()
    sub.endpoint = endpoint
    sub.p256dh = "p"
    sub.auth = "a"
    sub.failure_count = 0
    return sub


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


def test_vapid_private_key_rewrites_single_line_pem(monkeypatch: pytest.MonkeyPatch) -> None:
    single_line = VALID_VAPID_PEM.replace("\n", "")
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_private_key=single_line),
    )
    normalized = _vapid_private_key()
    assert "BEGIN" in normalized
    assert isinstance(_validated_vapid_private_key(), Vapid)


def test_vapid_accepts_raw_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_private_key=VALID_VAPID_RAW),
    )
    assert isinstance(_validated_vapid_private_key(), Vapid)


def test_vapid_accepts_pem_via_from_pem(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_private_key=VALID_VAPID_PEM),
    )
    assert isinstance(_validated_vapid_private_key(), Vapid)


def test_vapid_private_key_rewrites_escaped_newlines(monkeypatch: pytest.MonkeyPatch) -> None:
    escaped = VALID_VAPID_PEM.replace("\n", "\\n")
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_private_key=f'"{escaped}"'),
    )
    assert isinstance(_validated_vapid_private_key(), Vapid)


def test_vapid_private_key_accepts_base64url_pem_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    token = base64.urlsafe_b64encode(VALID_VAPID_PEM.encode()).decode().rstrip("=")
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_private_key=f"base64url:{token}"),
    )
    assert isinstance(_validated_vapid_private_key(), Vapid)


def test_vapid_private_key_recovers_plus_turned_into_space(monkeypatch: pytest.MonkeyPatch) -> None:
    corrupted = VALID_VAPID_PEM.replace("+", " ")
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(vapid_private_key=corrupted),
    )
    assert isinstance(_validated_vapid_private_key(), Vapid)


def test_rewrap_pem_roundtrip() -> None:
    body = "".join(VALID_VAPID_PEM.strip().split("\n")[1:-1])
    mangled = f"-----BEGIN PRIVATE KEY-----{body}-----END PRIVATE KEY-----"
    fixed = _rewrap_pem(mangled)
    serialization.load_pem_private_key(fixed.encode(), password=None)


def test_send_push_passes_vapid_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.notifications.settings", _vapid_settings())
    sub = _mock_sub()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [sub]

    with patch("pywebpush.webpush") as webpush_mock:
        result = send_push_to_user(db, uuid4(), {"title": "t"})
        webpush_mock.assert_called_once()
        assert webpush_mock.call_args.kwargs["timeout"] == PUSH_TIMEOUT_SECONDS
        assert webpush_mock.call_args.kwargs["vapid_claims"] == {"sub": "mailto:t@t"}
        assert isinstance(webpush_mock.call_args.kwargs["vapid_private_key"], Vapid)
        assert result["sent"] == 1
        assert result["error"] is None
        assert sub.failure_count == 0


def test_send_push_reports_invalid_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.notifications.settings",
        MagicMock(
            vapid_private_key="-----BEGIN PRIVATE KEY-----\nnot-a-key\n-----END PRIVATE KEY-----",
            vapid_public_key=VALID_VAPID_PUBLIC,
            vapid_contact_email="mailto:t@t",
        ),
    )
    result = send_push_to_user(MagicMock(), uuid4(), {"title": "t"})
    assert result["sent"] == 0
    assert "VAPID_PRIVATE_KEY" in (result["error"] or "")


def test_send_push_removes_gone_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    from pywebpush import WebPushException

    monkeypatch.setattr("app.services.notifications.settings", _vapid_settings())
    sub = _mock_sub()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [sub]

    response = MagicMock(status_code=410)
    with patch("pywebpush.webpush", side_effect=WebPushException("gone", response=response)):
        result = send_push_to_user(db, uuid4(), {"title": "t"})
    db.delete.assert_called_once_with(sub)
    assert result["sent"] == 0


def test_send_push_stops_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.notifications.settings", _vapid_settings())
    subs = [_mock_sub(f"https://web.push.apple.com/{i}") for i in range(5)]
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = subs

    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        return clock["t"]

    def slow_webpush(**_kwargs):
        clock["t"] += PUSH_BUDGET_SECONDS
        return None

    with (
        patch("app.services.notifications.time.monotonic", side_effect=fake_monotonic),
        patch("pywebpush.webpush", side_effect=slow_webpush) as webpush_mock,
    ):
        result = send_push_to_user(db, uuid4(), {"title": "t"})

    assert webpush_mock.call_count == 1
    assert result["sent"] == 1
    assert result["subscriptions"] == 5


def test_send_push_prunes_after_repeated_client_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from pywebpush import WebPushException

    monkeypatch.setattr("app.services.notifications.settings", _vapid_settings())
    sub = _mock_sub("https://web.push.apple.com/junk")
    sub.failure_count = MAX_PUSH_FAILURES - 1
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [sub]

    response = MagicMock(status_code=403)
    with patch("pywebpush.webpush", side_effect=WebPushException("forbidden", response=response)):
        result = send_push_to_user(db, uuid4(), {"title": "t"})

    db.delete.assert_called_once_with(sub)
    assert result["sent"] == 0


def test_subscribe_push_evicts_oldest_at_cap(db_session) -> None:
    user = User(
        email=f"cap-{uuid4().hex[:8]}@example.com",
        name="Cap User",
        password_hash="x",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    created_ids: list = []
    for i in range(MAX_PUSH_SUBSCRIPTIONS_PER_USER):
        sub = subscribe_push(
            db_session,
            user,
            PushSubscribeRequest(
                endpoint=f"https://web.push.apple.com/cap-{i}",
                p256dh="p",
                auth="a",
            ),
        )
        created_ids.append(sub.id)

    newest = subscribe_push(
        db_session,
        user,
        PushSubscribeRequest(
            endpoint="https://web.push.apple.com/cap-newest",
            p256dh="p",
            auth="a",
        ),
    )

    remaining = (
        db_session.query(PushSubscription)
        .filter(PushSubscription.user_id == user.id)
        .all()
    )
    assert len(remaining) == MAX_PUSH_SUBSCRIPTIONS_PER_USER
    remaining_ids = {s.id for s in remaining}
    assert created_ids[0] not in remaining_ids
    assert newest.id in remaining_ids


def test_is_in_quiet_hours_overnight() -> None:
    prefs = NotificationPreference(
        user_id=uuid4(),
        quiet_hours_start="22:00",
        quiet_hours_end="07:00",
    )
    assert is_in_quiet_hours(prefs, datetime(2026, 8, 16, 23, 0, tzinfo=timezone.utc))
    assert is_in_quiet_hours(prefs, datetime(2026, 8, 16, 6, 30, tzinfo=timezone.utc))
    assert not is_in_quiet_hours(prefs, datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc))


def test_is_in_quiet_hours_daytime_window() -> None:
    prefs = NotificationPreference(
        user_id=uuid4(),
        quiet_hours_start="09:00",
        quiet_hours_end="17:00",
    )
    assert is_in_quiet_hours(prefs, datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc))
    assert not is_in_quiet_hours(prefs, datetime(2026, 8, 16, 8, 0, tzinfo=timezone.utc))
