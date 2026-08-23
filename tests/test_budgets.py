from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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


def test_period_usage_spans_calendar_months(db_session: Session) -> None:
    family = Family(id=uuid4(), name="TZ Family", timezone="UTC")
    db_session.add(family)
    user_id = uuid4()
    for dt, amount in [
        (datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc), Decimal("10.00")),
        (datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc), Decimal("50.00")),
        (datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc), Decimal("25.00")),
        (datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc), Decimal("5.00")),
    ]:
        db_session.add(
            Expense(
                family_id=family.id,
                amount=amount,
                currency="EUR",
                category="Shopping",
                occurred_at=dt,
                created_by=user_id,
                source_type=SOURCE_MANUAL,
            )
        )
    db_session.commit()

    from app.models.budget import BudgetPeriod

    period = BudgetPeriod(
        family_id=family.id,
        start_date=date(2026, 8, 27),
        end_date=date(2026, 9, 26),
        label_month="2026-09",
        currency="EUR",
        created_by=user_id,
    )
    db_session.add(period)
    db_session.commit()

    usage = budget_service.period_usage(db_session, family, period)
    assert usage.get("Shopping") == Decimal("75.00")
    assert usage.get(None) == Decimal("75.00")


def test_current_period_empty(client: TestClient) -> None:
    headers = auth_headers(client, "budget-empty@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Budget Family", "timezone": "UTC"},
    ).json()["id"]
    res = client.get(f"/api/families/{family_id}/budget-periods/current", headers=headers)
    assert res.status_code == 200
    assert res.json() is None


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
    from app.models.budget import Budget, BudgetPeriod
    from app.models.user import User

    family = Family(id=uuid4(), name="Zero", timezone="UTC")
    user = User(id=uuid4(), email=f"{uuid4()}@ex.com", name="U", password_hash="x")
    db_session.add_all([family, user])
    today = date.today()
    period = BudgetPeriod(
        family_id=family.id,
        start_date=today.replace(day=1),
        end_date=today,
        label_month=f"{today.year:04d}-{today.month:02d}",
        currency="EUR",
        created_by=user.id,
    )
    db_session.add(period)
    db_session.flush()
    db_session.add(
        Budget(period_id=period.id, category=None, amount=Decimal("600.00"))
    )
    db_session.commit()

    summary = budget_service.overall_budget_summary(db_session, family)
    assert summary is not None
    assert summary.used == Decimal("0.00")
    assert summary.state == "ok"
    assert summary.percent_used == 0
    assert summary.period_id == period.id
    assert summary.start_date == period.start_date


def _current_window() -> tuple[str, str, str]:
    today = date.today()
    start = today - timedelta(days=5)
    end = today + timedelta(days=20)
    label = f"{end.year:04d}-{end.month:02d}"
    return start.isoformat(), end.isoformat(), label


def test_budget_period_create_patch_and_overlap(client: TestClient) -> None:
    headers = auth_headers(client, "budget-write@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Write Family", "timezone": "UTC"},
    ).json()["id"]

    start, end, label = _current_window()
    created = client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=headers,
        json={
            "start_date": start,
            "end_date": end,
            "budgets": [
                {"category": None, "amount": "1500.00"},
                {"category": "Shopping", "amount": "600.00"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    data = created.json()
    period_id = data["id"]
    assert data["label_month"] == label
    assert data["overall"] is not None
    assert float(data["overall"]["amount"]) == 1500.00
    assert len(data["categories"]) == 1
    shopping_id = data["categories"][0]["id"]

    patched = client.patch(
        f"/api/budgets/{shopping_id}",
        headers=headers,
        json={"amount": "650.00"},
    )
    assert patched.status_code == 200
    assert float(patched.json()["amount"]) == 650.00

    # Replacing budgets on PATCH (e.g. date edit from the sheet) must not
    # UniqueViolation on uq_budgets_period_overall.
    new_end = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    replaced = client.patch(
        f"/api/budget-periods/{period_id}",
        headers=headers,
        json={
            "start_date": start,
            "end_date": new_end,
            "label_month": new_end[:7],
            "budgets": [
                {"category": None, "amount": "1600.00"},
                {"category": "Shopping", "amount": "700.00"},
                {"category": "Dining", "amount": "200.00"},
            ],
        },
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["end_date"] == new_end
    assert float(replaced.json()["overall"]["amount"]) == 1600.00
    assert len(replaced.json()["categories"]) == 2

    overlap = client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=headers,
        json={
            "start_date": start,
            "end_date": end,
            "budgets": [{"category": "Dining", "amount": "100.00"}],
        },
    )
    assert overlap.status_code == 400

    next_start = (date.fromisoformat(new_end) + timedelta(days=1)).isoformat()
    next_end = (date.fromisoformat(new_end) + timedelta(days=30)).isoformat()
    upcoming = client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=headers,
        json={
            "start_date": next_start,
            "end_date": next_end,
            "budgets": [{"category": "Shopping", "amount": "700.00"}],
        },
    )
    assert upcoming.status_code == 201, upcoming.text

    deleted = client.delete(f"/api/budget-periods/{period_id}", headers=headers)
    assert deleted.status_code == 204


def test_child_cannot_set_budget_period(client: TestClient, db_session: Session) -> None:
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

    start, end, _ = _current_window()
    blocked = client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=child_headers,
        json={
            "start_date": start,
            "end_date": end,
            "budgets": [{"amount": "500.00"}],
        },
    )
    assert blocked.status_code == 403


def test_budget_alert_fires_once_at_eighty_percent(client: TestClient) -> None:
    headers = auth_headers(client, "budget-alert@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Alert Family", "timezone": "UTC"},
    ).json()["id"]

    start, end, _ = _current_window()
    client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=headers,
        json={
            "start_date": start,
            "end_date": end,
            "budgets": [{"category": "Shopping", "amount": "100.00"}],
        },
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

    spend = client.get(f"/api/families/{family_id}/spend", headers=headers).json()
    # overall household budget not set — spend.budget is null
    assert spend["budget"] is None


def test_spend_budget_reflects_current_cycle(client: TestClient) -> None:
    headers = auth_headers(client, "budget-cycle-spend@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Cycle Spend", "timezone": "UTC"},
    ).json()["id"]
    start, end, label = _current_window()
    client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=headers,
        json={
            "start_date": start,
            "end_date": end,
            "budgets": [{"amount": "600.00"}],
        },
    )
    spend = client.get(f"/api/families/{family_id}/spend", headers=headers).json()
    assert spend["budget"] is not None
    assert spend["budget"]["label_month"] == label
    assert spend["budget"]["start_date"] == start
    assert spend["budget"]["end_date"] == end
    assert float(spend["budget"]["amount"]) == 600.0


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
