from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models.notification import Notification
from app.workers.reminders import process_reminders
from tests.conftest import auth_headers


@pytest.fixture()
def reminder_session(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    """Point the reminder worker at the same in-memory DB as the API client."""
    TestingSessionLocal = sessionmaker(
        bind=db_session.get_bind(),
        autocommit=False,
        autoflush=False,
    )
    monkeypatch.setattr("app.workers.reminders.SessionLocal", TestingSessionLocal)
    return db_session


def test_task_due_soon_notifies_once(
    client: TestClient,
    reminder_session: Session,
) -> None:
    headers = auth_headers(client, "due-soon@example.com", name="Due")
    family = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Due Family", "timezone": "UTC"},
    ).json()
    family_id = family["id"]
    member_id = client.get(f"/api/families/{family_id}/members", headers=headers).json()[0]["id"]

    due_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    task = client.post(
        f"/api/families/{family_id}/tasks",
        headers=headers,
        json={
            "title": "Spam me",
            "assignee_ids": [member_id],
            "due_at": due_at.isoformat(),
        },
    )
    assert task.status_code == 200, task.text
    task_id = UUID(task.json()["id"])

    process_reminders()
    process_reminders()

    reminder_session.expire_all()
    due_soon = (
        reminder_session.query(Notification)
        .filter(
            Notification.entity_id == task_id,
            Notification.title == "Task due soon",
        )
        .all()
    )
    assert len(due_soon) == 1


def test_event_reminder_still_fires_once(
    client: TestClient,
    reminder_session: Session,
) -> None:
    headers = auth_headers(client, "cal-rem@example.com", name="Cal")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Cal Family", "timezone": "UTC"},
    ).json()["id"]

    starts = datetime.now(timezone.utc) + timedelta(minutes=30)
    event = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={
            "title": "Pickup",
            "starts_at": starts.isoformat(),
            "reminder_minutes": [30],
        },
    )
    assert event.status_code == 200, event.text
    event_id = UUID(event.json()["id"])

    process_reminders()
    process_reminders()

    reminder_session.expire_all()
    reminders = (
        reminder_session.query(Notification)
        .filter(
            Notification.entity_id == event_id,
            Notification.title == "Upcoming event",
        )
        .all()
    )
    assert len(reminders) == 1
