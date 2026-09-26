from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.rate_limit import reset_ip_limiter
from app.models.password_reset import PasswordResetToken
from app.services.email import ResendEmailSender, get_email_sender
from app.services.password_reset import hash_reset_token
from tests.conftest import auth_headers


def test_forgot_password_unknown_email_looks_the_same(client: TestClient) -> None:
    with patch("app.services.password_reset.try_send_password_reset_email") as send:
        unknown = client.post(
            "/api/auth/forgot-password",
            json={"email": "nobody@example.com"},
        )
        assert unknown.status_code == 200
        assert unknown.json() == {}
        send.assert_not_called()

    auth_headers(client, "known@example.com")
    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=True,
    ) as send:
        known = client.post(
            "/api/auth/forgot-password",
            json={"email": "known@example.com"},
        )
        assert known.status_code == 200
        assert known.json() == {}
        send.assert_called_once()


def test_forgot_password_sends_reset_link_and_resets(
    client: TestClient, db_session: Session
) -> None:
    headers = auth_headers(client, "resetme@example.com", password="password123")
    old_access = headers["Authorization"].split(" ", 1)[1]

    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=True,
    ) as send:
        res = client.post(
            "/api/auth/forgot-password",
            json={"email": "ResetMe@example.com"},
        )
        assert res.status_code == 200
        reset_url = send.call_args.kwargs["reset_url"]
        assert reset_url.startswith("http://localhost:3000/reset/")
        token = reset_url.rsplit("/", 1)[-1]

    stored = db_session.query(PasswordResetToken).one()
    assert stored.token_hash == hash_reset_token(token)
    assert "token" not in res.json()

    reset = client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "newpassword1"},
    )
    assert reset.status_code == 200
    new_access = reset.json()["access_token"]
    assert new_access != old_access

    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "resetme@example.com"

    stale = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {old_access}"},
    )
    assert stale.status_code == 401

    reused = client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "anotherpass1"},
    )
    assert reused.status_code == 400
    assert reused.json()["code"] == "invalid_reset_link"

    login = client.post(
        "/api/auth/login",
        json={"email": "resetme@example.com", "password": "newpassword1"},
    )
    assert login.status_code == 200


def test_reset_password_rejects_garbage_and_expired(
    client: TestClient, db_session: Session
) -> None:
    garbage = client.post(
        "/api/auth/reset-password",
        json={"token": "not-a-real-token", "password": "password123"},
    )
    assert garbage.status_code == 400
    assert garbage.json()["detail"] == "This link is invalid or expired."

    auth_headers(client, "expiring@example.com")
    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=True,
    ) as send:
        client.post("/api/auth/forgot-password", json={"email": "expiring@example.com"})
        token = send.call_args.kwargs["reset_url"].rsplit("/", 1)[-1]

    row = db_session.query(PasswordResetToken).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    expired = client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "password123"},
    )
    assert expired.status_code == 400
    assert expired.json()["code"] == "invalid_reset_link"


def test_forgot_password_cooldown_and_newest_wins(
    client: TestClient, db_session: Session
) -> None:
    auth_headers(client, "cool@example.com")
    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=True,
    ) as send:
        first = client.post("/api/auth/forgot-password", json={"email": "cool@example.com"})
        second = client.post("/api/auth/forgot-password", json={"email": "cool@example.com"})
        assert first.status_code == 200
        assert second.status_code == 200
        assert send.call_count == 1
        first_token = send.call_args.kwargs["reset_url"].rsplit("/", 1)[-1]

    row = db_session.query(PasswordResetToken).one()
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=16)
    db_session.commit()

    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=True,
    ) as send:
        client.post("/api/auth/forgot-password", json={"email": "cool@example.com"})
        assert send.call_count == 1
        second_token = send.call_args.kwargs["reset_url"].rsplit("/", 1)[-1]

    assert first_token != second_token
    old = client.post(
        "/api/auth/reset-password",
        json={"token": first_token, "password": "password123"},
    )
    assert old.status_code == 400
    new = client.post(
        "/api/auth/reset-password",
        json={"token": second_token, "password": "password123"},
    )
    assert new.status_code == 200


def test_login_cancels_outstanding_reset_link(client: TestClient) -> None:
    auth_headers(client, "cancel@example.com", password="password123")
    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=True,
    ) as send:
        client.post("/api/auth/forgot-password", json={"email": "cancel@example.com"})
        token = send.call_args.kwargs["reset_url"].rsplit("/", 1)[-1]

    login = client.post(
        "/api/auth/login",
        json={"email": "cancel@example.com", "password": "password123"},
    )
    assert login.status_code == 200

    reset = client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "newpassword1"},
    )
    assert reset.status_code == 400


def test_forgot_password_ip_cap_skips_send(client: TestClient) -> None:
    reset_ip_limiter.clear()
    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=True,
    ) as send:
        for i in range(10):
            client.post(
                "/api/auth/forgot-password",
                json={"email": f"missing{i}@example.com"},
            )
        auth_headers(client, "aftercap@example.com")
        capped = client.post(
            "/api/auth/forgot-password",
            json={"email": "aftercap@example.com"},
        )
        assert capped.status_code == 200
        send.assert_not_called()


def test_send_failure_allows_retry(client: TestClient) -> None:
    auth_headers(client, "failmail@example.com")
    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=False,
    ):
        first = client.post(
            "/api/auth/forgot-password",
            json={"email": "failmail@example.com"},
        )
        assert first.status_code == 200
    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=True,
    ) as send:
        second = client.post(
            "/api/auth/forgot-password",
            json={"email": "failmail@example.com"},
        )
        assert second.status_code == 200
        send.assert_called_once()


def test_reset_password_short_password_is_422(client: TestClient) -> None:
    res = client.post(
        "/api/auth/reset-password",
        json={"token": "abc", "password": "short"},
    )
    assert res.status_code == 422


def test_resend_sender_posts_to_resend_api(monkeypatch) -> None:
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        response = MagicMock()
        response.raise_for_status = lambda: None
        return response

    monkeypatch.setattr("app.services.email.httpx.post", fake_post)
    sender = ResendEmailSender(
        api_key="re_test",
        from_address="FamilyOS <noreply@stacklessdev.com>",
    )
    sender.send_password_reset_email(
        to="kayode@example.com",
        reset_url="http://localhost:3000/reset/tok",
    )
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer re_test"
    assert captured["json"]["from"] == "FamilyOS <noreply@stacklessdev.com>"
    assert captured["json"]["to"] == ["kayode@example.com"]
    assert "http://localhost:3000/reset/tok" in captured["json"]["text"]


def test_get_email_sender_falls_back_without_resend_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.email.get_settings",
        lambda: MagicMock(
            email_provider="resend",
            resend_api_key="  ",
            email_from="FamilyOS <noreply@stacklessdev.com>",
        ),
    )
    sender = get_email_sender()
    assert sender.__class__.__name__ == "LoggingEmailSender"


def test_refresh_rejects_old_version_after_reset(client: TestClient) -> None:
    headers = auth_headers(client, "ver@example.com", password="password123")
    login = client.post(
        "/api/auth/login",
        json={"email": "ver@example.com", "password": "password123"},
    )
    refresh = login.json()["refresh_token"]

    with patch(
        "app.services.password_reset.try_send_password_reset_email",
        return_value=True,
    ) as send:
        client.post("/api/auth/forgot-password", json={"email": "ver@example.com"})
        token = send.call_args.kwargs["reset_url"].rsplit("/", 1)[-1]

    client.post(
        "/api/auth/reset-password",
        json={"token": token, "password": "newpassword1"},
    )
    stale_refresh = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert stale_refresh.status_code == 401
