from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def _register(client: TestClient, email: str, name: str) -> tuple[dict, str]:
    res = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "name": name},
    )
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token


def _two_member_family(client: TestClient) -> tuple[str, dict, str, dict, str]:
    owner_headers, owner_token = _register(client, "ws-owner@example.com", "Owner")
    family = client.post(
        "/api/families",
        headers=owner_headers,
        json={"name": "Realtime Family", "timezone": "UTC"},
    )
    assert family.status_code == 200, family.text
    family_id = family.json()["id"]

    invite = client.post(
        f"/api/families/{family_id}/invitations",
        headers=owner_headers,
        json={"email": "ws-partner@example.com"},
    )
    assert invite.status_code == 200, invite.text
    invite_token = invite.json()["invite_token"]

    partner_headers, partner_token = _register(client, "ws-partner@example.com", "Partner")
    accept = client.post(f"/api/invitations/{invite_token}/accept", headers=partner_headers)
    assert accept.status_code == 200, accept.text
    return family_id, owner_headers, owner_token, partner_headers, partner_token


def _ws_url(family_id: str, token: str) -> str:
    return f"/api/ws/families/{family_id}?token={token}"


def _receive_until(ws, expected_type: str, *, limit: int = 10) -> dict:
    """Skip interleaved notification.created frames until the domain event arrives."""
    skippable = {
        "notification.created",
        "shopping.item.created",
        "shopping.item.updated",
        "shopping.item.completed",
    }
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == expected_type:
            return msg
        if msg["type"] in skippable:
            continue
        raise AssertionError(f"expected {expected_type}, got {msg['type']}")
    raise AssertionError(f"did not receive {expected_type} within {limit} frames")


def test_ws_bad_token_closes_4401(client: TestClient) -> None:
    family_id = str(uuid4())
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(_ws_url(family_id, "not-a-jwt")) as ws:
            ws.receive_text()
    assert exc_info.value.code == 4401


def test_ws_non_member_closes_4403(client: TestClient) -> None:
    owner_headers, _owner_token = _register(client, "ws-host@example.com", "Host")
    family_id = client.post(
        "/api/families",
        headers=owner_headers,
        json={"name": "Private Family", "timezone": "UTC"},
    ).json()["id"]
    _outsider_headers, outsider_token = _register(client, "ws-outsider@example.com", "Outsider")

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(_ws_url(family_id, outsider_token)) as ws:
            ws.receive_text()
    assert exc_info.value.code == 4403


def test_ws_shopping_item_broadcast_from_sync_route(client: TestClient) -> None:
    family_id, owner_headers, _owner_token, _partner_headers, partner_token = _two_member_family(
        client
    )
    list_id = client.get(
        f"/api/families/{family_id}/shopping-lists", headers=owner_headers
    ).json()[0]["id"]

    with client.websocket_connect(_ws_url(family_id, partner_token)) as ws:
        created = client.post(
            f"/api/shopping-lists/{list_id}/items",
            headers=owner_headers,
            json={"name": "Milk", "quantity": 1, "category": "Dairy"},
        )
        assert created.status_code == 200, created.text
        item_id = created.json()["id"]

        msg = _receive_until(ws, "shopping.item.created")
        assert msg["item"]["id"] == item_id
        assert msg["item"]["name"] == "Milk"

        patched = client.patch(
            f"/api/shopping-items/{item_id}",
            headers=owner_headers,
            json={"completed": True},
        )
        assert patched.status_code == 200, patched.text
        done = _receive_until(ws, "shopping.item.completed")
        assert done["item"]["id"] == item_id
        assert done["item"]["completed_at"] is not None

        deleted = client.delete(f"/api/shopping-items/{item_id}", headers=owner_headers)
        assert deleted.status_code == 204, deleted.text
        gone = _receive_until(ws, "shopping.item.updated")
        assert gone["deleted"] is True
        assert gone["item_id"] == item_id


def test_ws_shopping_session_basket_broadcast(client: TestClient) -> None:
    family_id, owner_headers, _owner_token, _partner_headers, partner_token = _two_member_family(
        client
    )
    list_id = client.get(
        f"/api/families/{family_id}/shopping-lists", headers=owner_headers
    ).json()[0]["id"]

    created = client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=owner_headers,
        json={"name": "Eggs", "category": "Dairy"},
    )
    assert created.status_code == 200
    item_id = created.json()["id"]

    with client.websocket_connect(_ws_url(family_id, partner_token)) as ws:
        added = client.post(
            f"/api/families/{family_id}/shopping-sessions/active/items",
            headers=owner_headers,
            json={"item_id": item_id},
        )
        assert added.status_code == 200
        session_item_id = added.json()["item"]["id"]

        started = _receive_until(ws, "shopping.session.started")
        assert started["session"]["status"] == "active"

        item_added = _receive_until(ws, "shopping.session.item.added")
        assert item_added["item"]["name"] == "Eggs"
        assert item_added["removed_item_id"] == item_id

        removed = client.delete(
            f"/api/shopping-session-items/{session_item_id}", headers=owner_headers
        )
        assert removed.status_code == 200
        item_removed = _receive_until(ws, "shopping.session.item.removed")
        assert item_removed["item_id"] == session_item_id
        assert item_removed["restored_item"]["name"] == "Eggs"


def test_ws_event_broadcast(client: TestClient) -> None:
    family_id, owner_headers, _owner_token, _partner_headers, partner_token = _two_member_family(
        client
    )
    starts = datetime.now(timezone.utc) + timedelta(hours=2)

    with client.websocket_connect(_ws_url(family_id, partner_token)) as ws:
        created = client.post(
            f"/api/families/{family_id}/events",
            headers=owner_headers,
            json={
                "title": "School pickup",
                "starts_at": starts.isoformat(),
                "ends_at": (starts + timedelta(hours=1)).isoformat(),
                "location": "School",
            },
        )
        assert created.status_code == 200, created.text
        event_id = created.json()["id"]

        msg = _receive_until(ws, "event.created")
        assert msg["event"]["id"] == event_id
        assert msg["event"]["title"] == "School pickup"

        patched = client.patch(
            f"/api/events/{event_id}",
            headers=owner_headers,
            json={"title": "School drop-off"},
        )
        assert patched.status_code == 200, patched.text
        updated = _receive_until(ws, "event.updated")
        assert updated["event"]["id"] == event_id
        assert updated["event"]["title"] == "School drop-off"

        deleted = client.delete(f"/api/events/{event_id}", headers=owner_headers)
        assert deleted.status_code == 204, deleted.text
        gone = _receive_until(ws, "event.deleted")
        assert gone["event_id"] == event_id


def test_ws_task_broadcast_including_recurring_complete(client: TestClient) -> None:
    family_id, owner_headers, _owner_token, _partner_headers, partner_token = _two_member_family(
        client
    )
    due = datetime.now(timezone.utc) + timedelta(hours=3)

    with client.websocket_connect(_ws_url(family_id, partner_token)) as ws:
        created = client.post(
            f"/api/families/{family_id}/tasks",
            headers=owner_headers,
            json={
                "title": "Pack bags",
                "priority": "high",
                "recurrence_rule": "weekly",
                "due_at": due.isoformat(),
            },
        )
        assert created.status_code == 200, created.text
        task_id = created.json()["id"]

        msg = _receive_until(ws, "task.created")
        assert msg["task"]["id"] == task_id
        assert msg["task"]["title"] == "Pack bags"

        patched = client.patch(
            f"/api/tasks/{task_id}",
            headers=owner_headers,
            json={"title": "Pack sports bags"},
        )
        assert patched.status_code == 200, patched.text
        updated = _receive_until(ws, "task.updated")
        assert updated["task"]["title"] == "Pack sports bags"

        complete = client.post(f"/api/tasks/{task_id}/complete", headers=owner_headers)
        assert complete.status_code == 200, complete.text
        completed_msg = _receive_until(ws, "task.updated")
        assert completed_msg["task"]["id"] == task_id
        assert completed_msg["task"]["completed_at"] is not None

        next_msg = _receive_until(ws, "task.created")
        assert next_msg["task"]["id"] != task_id
        assert next_msg["task"]["title"] == "Pack sports bags"
        assert next_msg["task"]["completed_at"] is None

        deleted = client.delete(f"/api/tasks/{next_msg['task']['id']}", headers=owner_headers)
        assert deleted.status_code == 204, deleted.text
        gone = _receive_until(ws, "task.deleted")
        assert gone["task_id"] == next_msg["task"]["id"]


def test_ws_leave_stops_broadcasts_and_blocks_reconnect(client: TestClient) -> None:
    family_id, owner_headers, _owner_token, partner_headers, partner_token = _two_member_family(
        client
    )
    list_id = client.get(
        f"/api/families/{family_id}/shopping-lists", headers=owner_headers
    ).json()[0]["id"]

    with client.websocket_connect(_ws_url(family_id, partner_token)) as ws:
        left = client.post(f"/api/families/{family_id}/leave", headers=partner_headers)
        assert left.status_code == 204, left.text

        created = client.post(
            f"/api/shopping-lists/{list_id}/items",
            headers=owner_headers,
            json={"name": "SECRET_AFTER_LEAVE", "quantity": 1},
        )
        assert created.status_code == 200, created.text

        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_json()
        assert exc_info.value.code == 4403

    with pytest.raises(WebSocketDisconnect) as reconnect_info:
        with client.websocket_connect(_ws_url(family_id, partner_token)) as ws:
            ws.receive_text()
    assert reconnect_info.value.code == 4403
