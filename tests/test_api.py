from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.event import MAX_EVENT_DESCRIPTION, MAX_EVENT_LOCATION
from tests.conftest import auth_headers


def test_health(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_register_login_me(client: TestClient) -> None:
    headers = auth_headers(client, "kayode@example.com", name="Kayode")
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "kayode@example.com"
    assert me.json()["name"] == "Kayode"

    login = client.post(
        "/api/auth/login",
        json={"email": "kayode@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()


def test_duplicate_register(client: TestClient) -> None:
    auth_headers(client, "dup@example.com")
    res = client.post(
        "/api/auth/register",
        json={"email": "dup@example.com", "password": "password123", "name": "Dup"},
    )
    assert res.status_code == 409


def test_family_create_members_invite_accept(client: TestClient) -> None:
    owner = auth_headers(client, "owner@example.com", name="Kayode")
    family = client.post(
        "/api/families",
        headers=owner,
        json={"name": "Ayelegun Family", "timezone": "Europe/Berlin"},
    )
    assert family.status_code == 200
    family_id = family.json()["id"]

    members = client.get(f"/api/families/{family_id}/members", headers=owner)
    assert members.status_code == 200
    assert len(members.json()) == 1
    assert members.json()[0]["role"] == "Owner"

    child = client.post(
        f"/api/families/{family_id}/members",
        headers=owner,
        json={"name": "Kita", "role": "Child"},
    )
    assert child.status_code == 200
    assert child.json()["user_id"] is None

    invite = client.post(
        f"/api/families/{family_id}/invitations",
        headers=owner,
        json={"email": "ade@example.com"},
    )
    assert invite.status_code == 200
    token = invite.json()["invite_token"]
    assert "token_hash" not in invite.json()
    assert invite.json()["invite_url"] == f"http://localhost:3000/invite/{token}"
    assert invite.json()["email"] == "ade@example.com"

    partner = auth_headers(client, "ade@example.com", name="Ade")
    accept = client.post(f"/api/invitations/{token}/accept", headers=partner)
    assert accept.status_code == 200
    assert accept.json()["member"]["role"] == "Parent"

    # Cross-family denial
    other = auth_headers(client, "other@example.com", name="Other")
    denied = client.get(f"/api/families/{family_id}/members", headers=other)
    assert denied.status_code == 404

    lists = client.get(f"/api/families/{family_id}/shopping-lists", headers=owner)
    assert lists.status_code == 200
    assert lists.json()[0]["name"] == "Groceries"

    locations = client.get(f"/api/families/{family_id}/shopping-locations", headers=owner)
    assert locations.status_code == 200
    assert [loc["name"] for loc in locations.json()] == [
        "REWE",
        "LIDL",
        "ALDI",
        "Rossmann",
        "DM",
        "African store",
    ]


def test_shopping_locations_crud_and_item_assignment(client: TestClient) -> None:
    owner = auth_headers(client, "locs-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": "Loc Family", "timezone": "UTC"},
    ).json()["id"]
    list_id = client.get(f"/api/families/{family_id}/shopping-lists", headers=owner).json()[0]["id"]

    created = client.post(
        f"/api/families/{family_id}/shopping-locations",
        headers=owner,
        json={"name": "JC Penney"},
    )
    assert created.status_code == 200
    loc_id = created.json()["id"]
    assert created.json()["name"] == "JC Penney"

    dup = client.post(
        f"/api/families/{family_id}/shopping-locations",
        headers=owner,
        json={"name": "JC Penney"},
    )
    assert dup.status_code == 409

    item = client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=owner,
        json={"name": "Socks", "category": "Other", "location_id": loc_id},
    )
    assert item.status_code == 200
    assert item.json()["location_id"] == loc_id
    item_id = item.json()["id"]

    other = auth_headers(client, "locs-other@example.com", name="Other")
    other_family_id = client.post(
        "/api/families",
        headers=other,
        json={"name": "Other Family", "timezone": "UTC"},
    ).json()["id"]
    other_loc_id = client.get(
        f"/api/families/{other_family_id}/shopping-locations", headers=other
    ).json()[0]["id"]

    cross = client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=owner,
        json={"name": "Bad", "location_id": other_loc_id},
    )
    assert cross.status_code == 400

    renamed = client.patch(
        f"/api/shopping-locations/{loc_id}",
        headers=owner,
        json={"name": "JCPenney"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "JCPenney"

    deleted = client.delete(f"/api/shopping-locations/{loc_id}", headers=owner)
    assert deleted.status_code == 204

    items = client.get(f"/api/shopping-lists/{list_id}/items", headers=owner)
    assert items.status_code == 200
    cleared = next(i for i in items.json() if i["id"] == item_id)
    assert cleared["location_id"] is None


def test_dashboard_calendar_tasks_shopping_notifications(client: TestClient) -> None:
    headers = auth_headers(client, "full@example.com", name="Kayode")
    family = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Test Family", "timezone": "UTC"},
    ).json()
    family_id = family["id"]
    members = client.get(f"/api/families/{family_id}/members", headers=headers).json()
    member_id = members[0]["id"]

    starts = datetime.now(timezone.utc) + timedelta(hours=2)
    event = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={
            "title": "School pickup",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
            "member_ids": [member_id],
            "reminder_minutes": [30],
            "location": "School",
        },
    )
    assert event.status_code == 200

    task = client.post(
        f"/api/families/{family_id}/tasks",
        headers=headers,
        json={
            "title": "Pack bags",
            "priority": "high",
            "category": "Child",
            "assignee_ids": [member_id],
            "recurrence_rule": "weekly",
            "due_at": starts.isoformat(),
        },
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    complete = client.post(f"/api/tasks/{task_id}/complete", headers=headers)
    assert complete.status_code == 200
    assert complete.json()["completed_at"] is not None

    open_tasks = client.get(f"/api/families/{family_id}/tasks?filter=open", headers=headers)
    assert open_tasks.status_code == 200
    # next weekly occurrence created
    assert any(t["title"] == "Pack bags" and t["completed_at"] is None for t in open_tasks.json())

    lists = client.get(f"/api/families/{family_id}/shopping-lists", headers=headers).json()
    list_id = lists[0]["id"]
    item = client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=headers,
        json={"name": "Milk", "quantity": 1, "category": "Dairy"},
    )
    assert item.status_code == 200
    item_id = item.json()["id"]

    done = client.patch(
        f"/api/shopping-items/{item_id}",
        headers=headers,
        json={"completed": True},
    )
    assert done.status_code == 200
    assert done.json()["completed_at"] is not None

    dash = client.get(f"/api/families/{family_id}/dashboard", headers=headers)
    assert dash.status_code == 200
    body = dash.json()
    assert body["family_name"] == "Test Family"
    assert "today_events" in body
    assert "open_tasks" in body

    prefs = client.get("/api/notification-preferences", headers=headers)
    assert prefs.status_code == 200
    assert prefs.json()["calendar_reminders"] is True

    notifs = client.get("/api/notifications", headers=headers)
    assert notifs.status_code == 200

    push = client.post(
        "/api/push/subscribe",
        headers=headers,
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/test-subscription",
            "p256dh": "p256dh-key",
            "auth": "auth-key",
        },
    )
    assert push.status_code == 200


def test_invite_token_stored_hashed_only(client: TestClient) -> None:
    headers = auth_headers(client, "hash@example.com")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Hash Family", "timezone": "UTC"},
    ).json()["id"]
    invite = client.post(
        f"/api/families/{family_id}/invitations",
        headers=headers,
        json={},
    ).json()
    assert invite["invite_token"]
    # raw token only returned once in response, not persisted as field name token
    assert "token" not in invite or invite.get("token") is None


def test_invite_with_email_succeeds_with_logging_mailer(client: TestClient) -> None:
    headers = auth_headers(client, "mailer-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Mail Family", "timezone": "UTC"},
    ).json()["id"]
    invite = client.post(
        f"/api/families/{family_id}/invitations",
        headers=headers,
        json={"email": "partner@example.com"},
    )
    assert invite.status_code == 200
    body = invite.json()
    assert body["email"] == "partner@example.com"
    assert body["invite_url"].startswith("http://localhost:3000/invite/")


def test_invite_accept_second_use_conflict(client: TestClient) -> None:
    owner = auth_headers(client, "invite-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": "Invite Once", "timezone": "UTC"},
    ).json()["id"]
    token = client.post(
        f"/api/families/{family_id}/invitations",
        headers=owner,
        json={},
    ).json()["invite_token"]

    first = auth_headers(client, "first-partner@example.com", name="First")
    assert client.post(f"/api/invitations/{token}/accept", headers=first).status_code == 200

    second = auth_headers(client, "second-partner@example.com", name="Second")
    reused = client.post(f"/api/invitations/{token}/accept", headers=second)
    assert reused.status_code == 409
    assert reused.json()["code"] == "invite_used"


def test_existing_member_accept_does_not_burn_invite(client: TestClient) -> None:
    owner = auth_headers(client, "burn-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": "No Burn", "timezone": "UTC"},
    ).json()["id"]
    token = client.post(
        f"/api/families/{family_id}/invitations",
        headers=owner,
        json={},
    ).json()["invite_token"]

    # Owner already belongs; accept must be idempotent and leave invite usable.
    self_accept = client.post(f"/api/invitations/{token}/accept", headers=owner)
    assert self_accept.status_code == 200
    assert self_accept.json()["member"]["role"] == "Owner"

    partner = auth_headers(client, "burn-partner@example.com", name="Partner")
    accept = client.post(f"/api/invitations/{token}/accept", headers=partner)
    assert accept.status_code == 200
    assert accept.json()["member"]["role"] == "Parent"


def test_reminder_minutes_validation(client: TestClient) -> None:
    headers = auth_headers(client, "rem-bounds@example.com", name="Rem")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Rem Family", "timezone": "UTC"},
    ).json()["id"]
    starts = datetime.now(timezone.utc) + timedelta(hours=2)
    base = {
        "title": "Bounded",
        "starts_at": starts.isoformat(),
    }

    too_many = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={**base, "reminder_minutes": list(range(11))},
    )
    assert too_many.status_code == 422

    negative = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={**base, "reminder_minutes": [-1]},
    )
    assert negative.status_code == 422

    too_large = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={**base, "reminder_minutes": [10081]},
    )
    assert too_large.status_code == 422

    deduped = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={**base, "reminder_minutes": [15, 15, 30]},
    )
    assert deduped.status_code == 200, deduped.text
    assert deduped.json()["reminder_minutes"] == [15, 30]


def test_events_list_window_limits(client: TestClient) -> None:
    headers = auth_headers(client, "window@example.com", name="Win")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Window Family", "timezone": "UTC"},
    ).json()["id"]

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2027, 1, 3, tzinfo=timezone.utc)  # > 366 days
    oversized = client.get(
        f"/api/families/{family_id}/events",
        headers=headers,
        params={"from": start.isoformat(), "to": end.isoformat()},
    )
    assert oversized.status_code == 400

    inverted = client.get(
        f"/api/families/{family_id}/events",
        headers=headers,
        params={"from": end.isoformat(), "to": start.isoformat()},
    )
    assert inverted.status_code == 400

    ok = client.get(
        f"/api/families/{family_id}/events",
        headers=headers,
        params={
            "from": start.isoformat(),
            "to": (start + timedelta(days=30)).isoformat(),
        },
    )
    assert ok.status_code == 200


def test_far_future_events_in_defaults_and_dashboard(client: TestClient) -> None:
    headers = auth_headers(client, "far-future@example.com", name="Far")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Far Family", "timezone": "UTC"},
    ).json()["id"]

    starts = datetime.now(timezone.utc) + timedelta(days=90)
    created = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={
            "title": "September trip",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=2)).isoformat(),
        },
    )
    assert created.status_code == 200
    event_id = created.json()["id"]

    listed = client.get(f"/api/families/{family_id}/events", headers=headers)
    assert listed.status_code == 200
    assert any(e["id"] == event_id for e in listed.json())

    dash = client.get(f"/api/families/{family_id}/dashboard", headers=headers)
    assert dash.status_code == 200
    assert any(e["id"] == event_id for e in dash.json()["upcoming_events"])


def test_event_description_and_location_length_limits(client: TestClient) -> None:
    headers = auth_headers(client, "event-len@example.com", name="Len")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Length Family", "timezone": "UTC"},
    ).json()["id"]
    starts = datetime.now(timezone.utc) + timedelta(hours=2)
    base = {
        "title": "Bounded fields",
        "starts_at": starts.isoformat(),
    }

    too_long_description = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={**base, "description": "d" * (MAX_EVENT_DESCRIPTION + 1)},
    )
    assert too_long_description.status_code == 422

    too_long_location = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={**base, "location": "l" * (MAX_EVENT_LOCATION + 1)},
    )
    assert too_long_location.status_code == 422

    created = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={
            **base,
            "description": "d" * MAX_EVENT_DESCRIPTION,
            "location": "l" * MAX_EVENT_LOCATION,
        },
    )
    assert created.status_code == 200, created.text
    event_id = created.json()["id"]
    assert created.json()["description"] == "d" * MAX_EVENT_DESCRIPTION
    assert created.json()["location"] == "l" * MAX_EVENT_LOCATION

    patch_description = client.patch(
        f"/api/events/{event_id}",
        headers=headers,
        json={"description": "d" * (MAX_EVENT_DESCRIPTION + 1)},
    )
    assert patch_description.status_code == 422

    patch_location = client.patch(
        f"/api/events/{event_id}",
        headers=headers,
        json={"location": "l" * (MAX_EVENT_LOCATION + 1)},
    )
    assert patch_location.status_code == 422


def test_recurring_event_list_caps_instances(client: TestClient) -> None:
    headers = auth_headers(client, "expand@example.com", name="Exp")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Expand Family", "timezone": "UTC"},
    ).json()["id"]
    starts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    created = client.post(
        f"/api/families/{family_id}/events",
        headers=headers,
        json={
            "title": "Daily standup",
            "description": "d" * MAX_EVENT_DESCRIPTION,
            "location": "l" * MAX_EVENT_LOCATION,
            "starts_at": starts.isoformat(),
            "recurrence_rule": "daily",
        },
    )
    assert created.status_code == 200, created.text

    listed = client.get(
        f"/api/families/{family_id}/events",
        headers=headers,
        params={
            "from": starts.isoformat(),
            "to": (starts + timedelta(days=365)).isoformat(),
        },
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) <= 200
    assert all(row["title"] == "Daily standup" for row in rows)


def test_owner_leave_dissolves_without_successor(client: TestClient) -> None:
    owner = auth_headers(client, "solo-owner@example.com", name="Solo")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": "Solo Family", "timezone": "UTC"},
    ).json()["id"]
    leave = client.post(f"/api/families/{family_id}/leave", headers=owner)
    assert leave.status_code == 204
    assert client.get(f"/api/families/{family_id}", headers=owner).status_code == 404
    assert client.get("/api/me/families", headers=owner).json() == []


def test_owner_leave_with_child_only_dissolves(client: TestClient) -> None:
    owner = auth_headers(client, "parent-child@example.com", name="Parent")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": "Parent Child Family", "timezone": "UTC"},
    ).json()["id"]
    child = client.post(
        f"/api/families/{family_id}/members",
        headers=owner,
        json={"name": "Kid", "role": "Child"},
    )
    assert child.status_code == 200

    leave = client.post(f"/api/families/{family_id}/leave", headers=owner)
    assert leave.status_code == 204
    assert client.get(f"/api/families/{family_id}", headers=owner).status_code == 404


def test_owner_leave_transfers_to_earliest_parent(client: TestClient) -> None:
    owner = auth_headers(client, "leave-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": "Transfer Family", "timezone": "UTC"},
    ).json()["id"]

    first_token = client.post(
        f"/api/families/{family_id}/invitations",
        headers=owner,
        json={},
    ).json()["invite_token"]
    first_parent = auth_headers(client, "leave-parent-a@example.com", name="ParentA")
    assert client.post(f"/api/invitations/{first_token}/accept", headers=first_parent).status_code == 200

    second_token = client.post(
        f"/api/families/{family_id}/invitations",
        headers=owner,
        json={},
    ).json()["invite_token"]
    second_parent = auth_headers(client, "leave-parent-b@example.com", name="ParentB")
    assert client.post(f"/api/invitations/{second_token}/accept", headers=second_parent).status_code == 200

    leave = client.post(f"/api/families/{family_id}/leave", headers=owner)
    assert leave.status_code == 204

    members = client.get(f"/api/families/{family_id}/members", headers=first_parent).json()
    by_name = {m["name"]: m for m in members}
    assert len(members) == 2
    assert by_name["ParentA"]["role"] == "Owner"
    assert by_name["ParentB"]["role"] == "Parent"


def test_owner_leave_transfers_to_parent(client: TestClient) -> None:
    owner = auth_headers(client, "leave-owner-single@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": "Transfer Family", "timezone": "UTC"},
    ).json()["id"]
    token = client.post(
        f"/api/families/{family_id}/invitations",
        headers=owner,
        json={},
    ).json()["invite_token"]
    parent = auth_headers(client, "leave-parent@example.com", name="Parent")
    assert client.post(f"/api/invitations/{token}/accept", headers=parent).status_code == 200

    leave = client.post(f"/api/families/{family_id}/leave", headers=owner)
    assert leave.status_code == 204

    members = client.get(f"/api/families/{family_id}/members", headers=parent).json()
    assert len(members) == 1
    assert members[0]["role"] == "Owner"
    assert members[0]["name"] == "Parent"


def test_owner_can_remove_member(client: TestClient) -> None:
    owner, partner, family_id, _, partner_member_id = _two_member_family(client, "kick")
    removed = client.delete(
        f"/api/families/{family_id}/members/{partner_member_id}",
        headers=owner,
    )
    assert removed.status_code == 204

    members = client.get(f"/api/families/{family_id}/members", headers=owner).json()
    assert len(members) == 1
    assert members[0]["name"] == "Owner"
    assert client.get(f"/api/families/{family_id}", headers=partner).status_code == 404


def test_parent_cannot_remove_member(client: TestClient) -> None:
    owner, partner, family_id, owner_member_id, _ = _two_member_family(client, "kick-parent")
    res = client.delete(
        f"/api/families/{family_id}/members/{owner_member_id}",
        headers=partner,
    )
    assert res.status_code == 403


def test_owner_cannot_remove_self(client: TestClient) -> None:
    owner, _, family_id, owner_member_id, _ = _two_member_family(client, "kick-self")
    res = client.delete(
        f"/api/families/{family_id}/members/{owner_member_id}",
        headers=owner,
    )
    assert res.status_code == 400
    assert res.json()["code"] == "cannot_remove_self"


def test_owner_can_delete_family(client: TestClient) -> None:
    owner, partner, family_id, _, _ = _two_member_family(client, "delete-fam")
    child = client.post(
        f"/api/families/{family_id}/members",
        headers=owner,
        json={"name": "Kid", "role": "Child"},
    )
    assert child.status_code == 200

    deleted = client.delete(f"/api/families/{family_id}", headers=owner)
    assert deleted.status_code == 204
    assert client.get(f"/api/families/{family_id}", headers=owner).status_code == 404
    assert client.get("/api/me/families", headers=owner).json() == []
    assert client.get("/api/me/families", headers=partner).json() == []


def test_parent_cannot_delete_family(client: TestClient) -> None:
    _, partner, family_id, _, _ = _two_member_family(client, "delete-parent")
    res = client.delete(f"/api/families/{family_id}", headers=partner)
    assert res.status_code == 403


def test_push_subscribe_rejects_ssrf_endpoints(client: TestClient) -> None:
    headers = auth_headers(client, "push@example.com")
    for endpoint in (
        "http://127.0.0.1:8080/internal",
        "https://127.0.0.1/push",
        "https://example.com/push/1",
        "https://evil.example/hook",
    ):
        res = client.post(
            "/api/push/subscribe",
            headers=headers,
            json={"endpoint": endpoint, "p256dh": "k", "auth": "a"},
        )
        assert res.status_code == 400, endpoint
        assert res.json()["code"] == "invalid_push_endpoint"

    ok = client.post(
        "/api/push/subscribe",
        headers=headers,
        json={
            "endpoint": "https://updates.push.services.mozilla.com/wpush/v2/abc",
            "p256dh": "k",
            "auth": "a",
        },
    )
    assert ok.status_code == 200


def _two_member_family(client: TestClient, prefix: str) -> tuple[dict, dict, str, str, str]:
    """Owner + partner family. Returns (owner_headers, partner_headers, family_id, owner_member_id, partner_member_id)."""
    owner = auth_headers(client, f"{prefix}-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": f"{prefix} Family", "timezone": "UTC"},
    ).json()["id"]
    invite = client.post(
        f"/api/families/{family_id}/invitations",
        headers=owner,
        json={},
    ).json()
    partner = auth_headers(client, f"{prefix}-partner@example.com", name="Partner")
    accept = client.post(f"/api/invitations/{invite['invite_token']}/accept", headers=partner)
    assert accept.status_code == 200
    members = client.get(f"/api/families/{family_id}/members", headers=owner).json()
    by_name = {m["name"]: m["id"] for m in members}
    return owner, partner, family_id, by_name["Owner"], by_name["Partner"]


def test_vapid_public_key_endpoint(client: TestClient, monkeypatch) -> None:
    headers = auth_headers(client, "vapid@example.com")
    monkeypatch.setattr("app.services.notifications.settings.vapid_public_key", "")
    empty = client.get("/api/push/vapid-public-key", headers=headers)
    assert empty.status_code == 200
    assert empty.json() == {"public_key": None}

    monkeypatch.setattr(
        "app.services.notifications.settings.vapid_public_key",
        "BPublicKeyExample",
    )
    filled = client.get("/api/push/vapid-public-key", headers=headers)
    assert filled.status_code == 200
    assert filled.json() == {"public_key": "BPublicKeyExample"}


def test_event_create_notifies_other_member_not_actor(client: TestClient) -> None:
    owner, partner, family_id, _, _ = _two_member_family(client, "evt")
    starts = datetime.now(timezone.utc) + timedelta(hours=2)
    res = client.post(
        f"/api/families/{family_id}/events",
        headers=owner,
        json={
            "title": "Dentist",
            "starts_at": starts.isoformat(),
            "ends_at": (starts + timedelta(hours=1)).isoformat(),
        },
    )
    assert res.status_code == 200

    partner_notifs = client.get("/api/notifications", headers=partner).json()
    calendar = [n for n in partner_notifs if n["type"] == "calendar" and n["title"] == "New event"]
    assert len(calendar) == 1
    assert calendar[0]["body"] == "Dentist"

    owner_notifs = client.get("/api/notifications", headers=owner).json()
    assert not any(n["title"] == "New event" for n in owner_notifs)


def test_shopping_add_and_bought_notify_other_member(client: TestClient) -> None:
    owner, partner, family_id, _, _ = _two_member_family(client, "shop")
    list_id = client.get(f"/api/families/{family_id}/shopping-lists", headers=owner).json()[0]["id"]

    item = client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=owner,
        json={"name": "Milk", "quantity": 1},
    )
    assert item.status_code == 200
    item_id = item.json()["id"]

    partner_notifs = client.get("/api/notifications", headers=partner).json()
    added = [n for n in partner_notifs if n["type"] == "shopping" and "added" in n["body"]]
    assert len(added) == 1
    assert "Milk" in added[0]["body"]

    rename = client.patch(
        f"/api/shopping-items/{item_id}",
        headers=owner,
        json={"name": "Oat milk"},
    )
    assert rename.status_code == 200
    after_rename = client.get("/api/notifications", headers=partner).json()
    assert len([n for n in after_rename if n["type"] == "shopping"]) == 1

    bought = client.patch(
        f"/api/shopping-items/{item_id}",
        headers=owner,
        json={"completed": True},
    )
    assert bought.status_code == 200
    after_bought = client.get("/api/notifications", headers=partner).json()
    bought_notifs = [n for n in after_bought if n["type"] == "shopping" and "bought" in n["body"]]
    assert len(bought_notifs) == 1

    owner_notifs = client.get("/api/notifications", headers=owner).json()
    assert not any(n["type"] == "shopping" for n in owner_notifs)


def test_task_reassign_notifies_newly_assigned_only(client: TestClient) -> None:
    owner, partner, family_id, owner_mid, partner_mid = _two_member_family(client, "reassign")
    third = auth_headers(client, "reassign-third@example.com", name="Third")
    invite = client.post(f"/api/families/{family_id}/invitations", headers=owner, json={}).json()
    client.post(f"/api/invitations/{invite['invite_token']}/accept", headers=third)
    members = client.get(f"/api/families/{family_id}/members", headers=owner).json()
    third_mid = next(m["id"] for m in members if m["name"] == "Third")

    task = client.post(
        f"/api/families/{family_id}/tasks",
        headers=owner,
        json={"title": "Pack bags", "assignee_ids": [partner_mid]},
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    partner_first = client.get("/api/notifications", headers=partner).json()
    assert sum(1 for n in partner_first if n["title"] == "Task assigned") == 1

    reassign = client.patch(
        f"/api/tasks/{task_id}",
        headers=owner,
        json={"assignee_ids": [partner_mid, third_mid]},
    )
    assert reassign.status_code == 200

    partner_after = client.get("/api/notifications", headers=partner).json()
    assert sum(1 for n in partner_after if n["title"] == "Task assigned") == 1

    third_notifs = client.get("/api/notifications", headers=third).json()
    assigned = [n for n in third_notifs if n["title"] == "Task assigned"]
    assert len(assigned) == 1
    assert "Pack bags" in assigned[0]["body"]

    # Re-assign only to owner (actor) — no new partner/third assignment notifs
    client.patch(
        f"/api/tasks/{task_id}",
        headers=owner,
        json={"assignee_ids": [owner_mid]},
    )
    partner_final = client.get("/api/notifications", headers=partner).json()
    assert sum(1 for n in partner_final if n["title"] == "Task assigned") == 1


def test_invite_accept_notifies_existing_members(client: TestClient) -> None:
    owner = auth_headers(client, "join-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": "Join Family", "timezone": "UTC"},
    ).json()["id"]
    invite = client.post(f"/api/families/{family_id}/invitations", headers=owner, json={}).json()
    token = invite["invite_token"]

    joiner = auth_headers(client, "join-new@example.com", name="NewParent")
    accept = client.post(f"/api/invitations/{token}/accept", headers=joiner)
    assert accept.status_code == 200

    owner_notifs = client.get("/api/notifications", headers=owner).json()
    family = [n for n in owner_notifs if n["type"] == "family"]
    assert len(family) == 1
    assert "NewParent joined the family" in family[0]["body"]

    joiner_notifs = client.get("/api/notifications", headers=joiner).json()
    assert not any(n["type"] == "family" for n in joiner_notifs)

    # Already-a-member accept is idempotent and must not notify again
    again = client.post(f"/api/invitations/{token}/accept", headers=joiner)
    assert again.status_code == 200
    owner_again = client.get("/api/notifications", headers=owner).json()
    assert sum(1 for n in owner_again if n["type"] == "family") == 1


def test_preference_off_skips_notification_and_push(client: TestClient, monkeypatch) -> None:
    owner, partner, family_id, _, _ = _two_member_family(client, "prefs")
    client.patch(
        "/api/notification-preferences",
        headers=partner,
        json={"calendar_reminders": False, "shopping_activity": False},
    )

    push_calls: list = []

    def fake_webpush(**kwargs):
        push_calls.append(kwargs)

    monkeypatch.setattr(
        "app.services.notifications.settings.vapid_private_key",
        "priv",
    )
    monkeypatch.setattr(
        "app.services.notifications.settings.vapid_public_key",
        "pub",
    )
    monkeypatch.setattr("pywebpush.webpush", fake_webpush)

    client.post(
        "/api/push/subscribe",
        headers=partner,
        json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/test-pref",
            "p256dh": "p",
            "auth": "a",
        },
    )

    starts = datetime.now(timezone.utc) + timedelta(hours=1)
    client.post(
        f"/api/families/{family_id}/events",
        headers=owner,
        json={"title": "Silent", "starts_at": starts.isoformat()},
    )
    list_id = client.get(f"/api/families/{family_id}/shopping-lists", headers=owner).json()[0]["id"]
    client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=owner,
        json={"name": "Bread"},
    )

    partner_notifs = client.get("/api/notifications", headers=partner).json()
    assert not any(n["type"] in ("calendar", "shopping") for n in partner_notifs)
    assert push_calls == []


def test_shopping_session_basket_flow(client: TestClient) -> None:
    headers = auth_headers(client, "session-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Session Family", "timezone": "UTC"},
    ).json()["id"]
    list_id = client.get(f"/api/families/{family_id}/shopping-lists", headers=headers).json()[0]["id"]

    item_a = client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=headers,
        json={"name": "Milk", "category": "Dairy", "quantity": 2},
    )
    assert item_a.status_code == 200
    item_a_id = item_a.json()["id"]

    item_b = client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=headers,
        json={"name": "Bread", "category": "Other"},
    )
    assert item_b.status_code == 200
    item_b_id = item_b.json()["id"]

    active_empty = client.get(
        f"/api/families/{family_id}/shopping-sessions/active", headers=headers
    )
    assert active_empty.status_code == 200
    assert active_empty.json() is None

    added = client.post(
        f"/api/families/{family_id}/shopping-sessions/active/items",
        headers=headers,
        json={"item_id": item_a_id},
    )
    assert added.status_code == 200
    session_id = added.json()["session"]["id"]
    session_item_id = added.json()["item"]["id"]
    assert added.json()["session"]["status"] == "active"
    assert added.json()["session"]["item_count"] == 1

    items = client.get(f"/api/shopping-lists/{list_id}/items", headers=headers)
    assert items.status_code == 200
    assert all(i["id"] != item_a_id for i in items.json())
    assert any(i["id"] == item_b_id for i in items.json())

    active = client.get(f"/api/families/{family_id}/shopping-sessions/active", headers=headers)
    assert active.status_code == 200
    assert active.json()["id"] == session_id
    assert active.json()["item_count"] == 1

    removed = client.delete(f"/api/shopping-session-items/{session_item_id}", headers=headers)
    assert removed.status_code == 200
    assert removed.json()["restored_item"]["name"] == "Milk"

    items_after_undo = client.get(f"/api/shopping-lists/{list_id}/items", headers=headers)
    assert any(i["name"] == "Milk" for i in items_after_undo.json())

    active_after_undo = client.get(
        f"/api/families/{family_id}/shopping-sessions/active", headers=headers
    )
    assert active_after_undo.json()["item_count"] == 0

    empty_complete = client.post(
        f"/api/families/{family_id}/shopping-sessions/active/complete",
        headers=headers,
        json={"total_cost": "10.00"},
    )
    assert empty_complete.status_code == 400

    milk_id = next(i["id"] for i in items_after_undo.json() if i["name"] == "Milk")
    client.post(
        f"/api/families/{family_id}/shopping-sessions/active/items",
        headers=headers,
        json={"item_id": milk_id},
    )
    client.post(
        f"/api/families/{family_id}/shopping-sessions/active/items",
        headers=headers,
        json={"item_id": item_b_id},
    )

    completed = client.post(
        f"/api/families/{family_id}/shopping-sessions/active/complete",
        headers=headers,
        json={"total_cost": "42.50"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert float(completed.json()["total_cost"]) == 42.50
    assert completed.json()["item_count"] == 2

    active_cleared = client.get(
        f"/api/families/{family_id}/shopping-sessions/active", headers=headers
    )
    assert active_cleared.json() is None

    history = client.get(f"/api/families/{family_id}/shopping-sessions", headers=headers)
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["item_count"] == 2

    detail = client.get(f"/api/shopping-sessions/{session_id}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["items"]) == 2
    assert {i["name"] for i in detail.json()["items"]} == {"Milk", "Bread"}

    remaining = client.get(f"/api/shopping-lists/{list_id}/items", headers=headers)
    assert remaining.status_code == 200
    assert len(remaining.json()) == 0


def _add_and_complete_trip(
    client: TestClient,
    headers: dict,
    family_id: str,
    list_id: str,
    name: str,
    cost: str,
) -> dict:
    item = client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=headers,
        json={"name": name},
    )
    assert item.status_code == 200
    added = client.post(
        f"/api/families/{family_id}/shopping-sessions/active/items",
        headers=headers,
        json={"item_id": item.json()["id"]},
    )
    assert added.status_code == 200
    completed = client.post(
        f"/api/families/{family_id}/shopping-sessions/active/complete",
        headers=headers,
        json={"total_cost": cost},
    )
    assert completed.status_code == 200
    return completed.json()


def test_shopping_spend_monthly_totals(client: TestClient) -> None:
    headers = auth_headers(client, "spend-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Spend Family", "timezone": "UTC"},
    ).json()["id"]
    list_id = client.get(f"/api/families/{family_id}/shopping-lists", headers=headers).json()[0]["id"]

    empty = client.get(f"/api/families/{family_id}/shopping-spend?months=3", headers=headers)
    assert empty.status_code == 200
    body = empty.json()
    assert len(body["months"]) == 3
    assert body["currency"] == "EUR"
    assert all(float(row["total"]) == 0 for row in body["months"])
    assert float(body["year_to_date_total"]) == 0
    assert body["months"][-1]["month"] == body["current_month"]

    _add_and_complete_trip(client, headers, family_id, list_id, "Milk", "10.00")
    _add_and_complete_trip(client, headers, family_id, list_id, "Bread", "5.50")

    spend = client.get(f"/api/families/{family_id}/shopping-spend?months=3", headers=headers)
    assert spend.status_code == 200
    data = spend.json()
    current = data["months"][-1]
    assert float(current["total"]) == 15.50
    assert current["trip_count"] == 2
    assert float(current["average"]) == 7.75
    assert float(data["year_to_date_total"]) == 15.50
    assert data["months"][0]["trip_count"] == 0

    month = data["current_month"]
    history = client.get(
        f"/api/families/{family_id}/shopping-sessions?month={month}",
        headers=headers,
    )
    assert history.status_code == 200
    assert len(history.json()) == 2

    other = client.get(
        f"/api/families/{family_id}/shopping-sessions?month=2020-01",
        headers=headers,
    )
    assert other.status_code == 200
    assert other.json() == []

    bad = client.get(
        f"/api/families/{family_id}/shopping-sessions?month=2026-13",
        headers=headers,
    )
    assert bad.status_code == 400


def test_shopping_spend_timezone_month_bucket(client: TestClient, db_session: Session) -> None:
    from uuid import UUID

    from app.models.shopping_session import ShoppingSession

    headers = auth_headers(client, "tz-spend@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Berlin Spend", "timezone": "Europe/Berlin"},
    ).json()["id"]
    list_id = client.get(f"/api/families/{family_id}/shopping-lists", headers=headers).json()[0]["id"]
    trip = _add_and_complete_trip(client, headers, family_id, list_id, "Coffee", "8.00")

    session = db_session.get(ShoppingSession, UUID(trip["id"]))
    assert session is not None
    session.completed_at = datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc)
    db_session.commit()

    spend = client.get(f"/api/families/{family_id}/shopping-spend?months=12", headers=headers)
    assert spend.status_code == 200
    by_month = {row["month"]: row for row in spend.json()["months"]}
    assert float(by_month["2026-08"]["total"]) == 8.00
    assert by_month["2026-08"]["trip_count"] == 1
    assert by_month["2026-07"]["trip_count"] == 0

    august = client.get(
        f"/api/families/{family_id}/shopping-sessions?month=2026-08",
        headers=headers,
    )
    july = client.get(
        f"/api/families/{family_id}/shopping-sessions?month=2026-07",
        headers=headers,
    )
    assert len(august.json()) == 1
    assert july.json() == []

