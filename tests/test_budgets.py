from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.budget import Budget
from app.models.expense import Expense, SOURCE_MANUAL
from app.models.family import Family
from app.services import budget as budget_service
from app.services.budget import derive_state
from tests.conftest import auth_headers
from tests.test_api import _two_member_family


def test_derive_state_thresholds() -> None:
    assert derive_state(Decimal("79"), Decimal("100")) == (79, "ok")
    assert derive_state(Decimal("80"), Decimal("100")) == (80, "warning")
    assert derive_state(Decimal("99"), Decimal("100")) == (99, "warning")
    assert derive_state(Decimal("100"), Decimal("100")) == (100, "over")
    assert derive_state(Decimal("120"), Decimal("100")) == (120, "over")


def test_month_usage_respects_family_timezone(db_session: Session) -> None:
    family = Family(id=uuid4(), name="TZ Family", timezone="UTC")
    db_session.add(family)
    user_id = uuid4()
    db_session.add(
        Expense(
            family_id=family.id,
            amount=Decimal("50.00"),
            currency="EUR",
            category="Shopping",
            occurred_at=datetime(2026, 2, 15, 12, 0, tzinfo=timezone.utc),
            created_by=user_id,
            source_type=SOURCE_MANUAL,
        )
    )
    db_session.commit()

    usage = budget_service.month_usage(db_session, family, "2026-02")
    assert usage.get("Shopping", Decimal("0")) == Decimal("50.00")

    usage_jan = budget_service.month_usage(db_session, family, "2026-01")
    assert usage_jan.get("Shopping", Decimal("0")) == Decimal("0.00")


def test_list_budgets_empty(client: TestClient) -> None:
    headers = auth_headers(client, "budget-empty@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Budget Family", "timezone": "UTC"},
    ).json()["id"]
    res = client.get(f"/api/families/{family_id}/budgets", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["overall"] is None
    assert data["categories"] == []


def test_spend_includes_null_budget_when_unset(client: TestClient) -> None:
    headers = auth_headers(client, "budget-spend-null@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Spend Family", "timezone": "UTC"},
    ).json()["id"]
    spend = client.get(f"/api/families/{family_id}/spend", headers=headers)
    assert spend.status_code == 200
    assert spend.json()["budget"] is None


def test_overall_budget_summary_zero_spend(db_session: Session) -> None:
    family = Family(id=uuid4(), name="Zero", timezone="UTC")
    user_id = uuid4()
    db_session.add(family)
    db_session.add(
        Budget(
            family_id=family.id,
            category=None,
            amount=Decimal("600.00"),
            currency="EUR",
            created_by=user_id,
        )
    )
    db_session.commit()

    summary = budget_service.overall_budget_summary(db_session, family, month="2026-08")
    assert summary is not None
    assert summary.used == Decimal("0.00")
    assert summary.state == "ok"
    assert summary.percent_used == 0


def test_budget_upsert_and_patch(client: TestClient) -> None:
    headers = auth_headers(client, "budget-write@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Write Family", "timezone": "UTC"},
    ).json()["id"]

    created = client.post(
        f"/api/families/{family_id}/budgets",
        headers=headers,
        json={"category": "Shopping", "amount": "600.00"},
    )
    assert created.status_code == 201
    budget_id = created.json()["id"]
    assert float(created.json()["amount"]) == 600.00

    updated = client.post(
        f"/api/families/{family_id}/budgets",
        headers=headers,
        json={"category": "Shopping", "amount": "700.00"},
    )
    assert updated.status_code == 200
    assert updated.json()["id"] == budget_id
    assert float(updated.json()["amount"]) == 700.00

    patched = client.patch(
        f"/api/budgets/{budget_id}",
        headers=headers,
        json={"amount": "650.00"},
    )
    assert patched.status_code == 200
    assert float(patched.json()["amount"]) == 650.00

    deleted = client.delete(f"/api/budgets/{budget_id}", headers=headers)
    assert deleted.status_code == 204


def test_child_cannot_set_budget(client: TestClient, db_session: Session) -> None:
    from uuid import UUID

    from app.models.family import FamilyMember
    from app.models.user import User

    owner = auth_headers(client, "budget-owner@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=owner,
        json={"name": "Role Family", "timezone": "UTC"},
    ).json()["id"]

    child_headers = auth_headers(client, "child-user@example.com", name="Child User")
    child_user = db_session.query(User).filter(User.email == "child-user@example.com").one()
    db_session.add(
        FamilyMember(
            family_id=UUID(family_id),
            user_id=child_user.id,
            name="Child User",
            role="Child",
        )
    )
    db_session.commit()

    blocked = client.post(
        f"/api/families/{family_id}/budgets",
        headers=child_headers,
        json={"amount": "500.00"},
    )
    assert blocked.status_code == 403


def test_budget_alert_fires_once_at_eighty_percent(client: TestClient, db_session: Session) -> None:
    headers = auth_headers(client, "budget-alert@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Alert Family", "timezone": "UTC"},
    ).json()["id"]

    client.post(
        f"/api/families/{family_id}/budgets",
        headers=headers,
        json={"category": "Shopping", "amount": "100.00"},
    )

    client.post(
        f"/api/families/{family_id}/expenses",
        headers=headers,
        json={"amount": "85.00", "category": "Shopping"},
    )
    notifs = client.get("/api/notifications", headers=headers).json()
    budget_notifs = [n for n in notifs if n["type"] == "budget"]
    assert len(budget_notifs) == 1
    assert budget_notifs[0]["title"] == "Budget warning"

    client.post(
        f"/api/families/{family_id}/expenses",
        headers=headers,
        json={"amount": "5.00", "category": "Shopping"},
    )
    notifs2 = client.get("/api/notifications", headers=headers).json()
    budget_notifs2 = [n for n in notifs2 if n["type"] == "budget"]
    assert len(budget_notifs2) == 1


def test_shopping_notification_still_excludes_actor(client: TestClient) -> None:
    owner, partner, family_id, _, _ = _two_member_family(client, "budget-shop-exclude")
    list_id = client.get(f"/api/families/{family_id}/shopping-lists", headers=owner).json()[0]["id"]
    item = client.post(
        f"/api/shopping-lists/{list_id}/items",
        headers=owner,
        json={"name": "Milk"},
    ).json()
    client.post(
        f"/api/families/{family_id}/shopping-sessions/active/items",
        headers=owner,
        json={"shopping_item_id": item["id"]},
    )
    client.post(
        f"/api/families/{family_id}/shopping-sessions/active/complete",
        headers=owner,
        json={"total_cost": "5.00"},
    )
    owner_notifs = client.get("/api/notifications", headers=owner).json()
    partner_notifs = client.get("/api/notifications", headers=partner).json()
    owner_shopping = [n for n in owner_notifs if n["type"] == "shopping"]
    partner_shopping = [n for n in partner_notifs if n["type"] == "shopping"]
    assert len(owner_shopping) == 0
    assert len(partner_shopping) == 1

