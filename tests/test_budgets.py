from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.budget import Budget, BudgetPeriod
from app.models.budget_group import GROUP_FIXED, GROUP_INCOME
from app.models.expense import Expense, SOURCE_MANUAL
from app.models.family import Family
from app.models.user import User
from app.services import budget as budget_service
from app.services import budget_subcategory as subcategory_service
from app.services.budget import derive_state
from tests.conftest import auth_headers


def test_derive_state_thresholds() -> None:
    assert derive_state(Decimal("79"), Decimal("100")) == (79, "ok")
    assert derive_state(Decimal("80"), Decimal("100")) == (80, "warning")
    assert derive_state(Decimal("99"), Decimal("100")) == (99, "warning")
    assert derive_state(Decimal("100"), Decimal("100")) == (100, "over")
    assert derive_state(Decimal("120"), Decimal("100")) == (120, "over")


def _seed_family_with_groceries(db: Session) -> tuple[Family, User, object]:
    family = Family(id=uuid4(), name="TZ Family", timezone="UTC")
    user = User(id=uuid4(), email=f"{uuid4()}@ex.com", name="U", password_hash="x")
    db.add_all([family, user])
    db.commit()
    groceries = subcategory_service.groceries_subcategory(db, family.id)
    return family, user, groceries


def test_period_usage_by_subcategory(db_session: Session) -> None:
    family, user, groceries = _seed_family_with_groceries(db_session)
    for dt, amount in [
        (datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc), Decimal("50.00")),
        (datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc), Decimal("25.00")),
        (datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc), Decimal("5.00")),
    ]:
        db_session.add(
            Expense(
                family_id=family.id,
                amount=amount,
                currency="EUR",
                subcategory_id=groceries.id,
                occurred_at=dt,
                created_by=user.id,
                source_type=SOURCE_MANUAL,
            )
        )
    period = BudgetPeriod(
        family_id=family.id,
        start_date=date(2026, 8, 27),
        end_date=date(2026, 9, 26),
        label_month="2026-09",
        currency="EUR",
        created_by=user.id,
    )
    db_session.add(period)
    db_session.commit()

    used, _ = budget_service.period_usage(db_session, family, period)
    assert used.get(groceries.id) == Decimal("75.00")


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


def test_create_period_with_subcategories(client: TestClient) -> None:
    headers = auth_headers(client, "budget-create@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Create Family", "timezone": "UTC"},
    ).json()["id"]
    subs = client.get(f"/api/families/{family_id}/budget-subcategories", headers=headers).json()
    groceries = next(
        s for g in subs["groups"] if g["group"] == GROUP_FIXED for s in g["subcategories"] if s["role"] == "groceries"
    )
    income_group = next(g for g in subs["groups"] if g["group"] == GROUP_INCOME)
    salary = client.post(
        f"/api/families/{family_id}/budget-subcategories",
        headers=headers,
        json={"group": GROUP_INCOME, "name": "Salary"},
    ).json()

    today = date.today()
    start = today.replace(day=1)
    end = today
    res = client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=headers,
        json={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "budgets": [
                {"subcategory_id": salary["id"], "amount": "3000.00"},
                {"subcategory_id": groceries["id"], "amount": "400.00"},
            ],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["summary"]["income_expected"] == "3000.00"
    assert body["summary"]["total_expenses_expected"] == "400.00"
    assert body["summary"]["left_over_expected"] == "2600.00"
    assert len(income_group["subcategories"]) >= 0


def test_settle_and_unsettle(client: TestClient) -> None:
    headers = auth_headers(client, "budget-settle@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Settle Family", "timezone": "UTC"},
    ).json()["id"]
    subs = client.get(f"/api/families/{family_id}/budget-subcategories", headers=headers).json()
    rent = client.post(
        f"/api/families/{family_id}/budget-subcategories",
        headers=headers,
        json={"group": GROUP_FIXED, "name": "Rent"},
    ).json()
    today = date.today()
    period = client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=headers,
        json={
            "start_date": today.replace(day=1).isoformat(),
            "end_date": today.isoformat(),
            "budgets": [{"subcategory_id": rent["id"], "amount": "100.00"}],
        },
    ).json()
    line = next(l for g in period["groups"] for l in g["lines"] if l["subcategory_id"] == rent["id"])
    settled = client.post(f"/api/budgets/{line['id']}/settle", headers=headers)
    assert settled.status_code == 200, settled.text
    settled_line = next(
        l for g in settled.json()["groups"] for l in g["lines"] if l["id"] == line["id"]
    )
    assert settled_line["settled"] is True
    assert settled_line["used"] == "100.00"

    unsettled = client.delete(f"/api/budgets/{line['id']}/settle", headers=headers)
    assert unsettled.status_code == 200
    unsettled_line = next(
        l for g in unsettled.json()["groups"] for l in g["lines"] if l["id"] == line["id"]
    )
    assert unsettled_line["settled"] is False
    assert unsettled_line["used"] == "0.00"
    assert len(subs["groups"]) >= 6


def test_copy_period(client: TestClient) -> None:
    headers = auth_headers(client, "budget-copy@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Copy Family", "timezone": "UTC"},
    ).json()["id"]
    rent = client.post(
        f"/api/families/{family_id}/budget-subcategories",
        headers=headers,
        json={"group": GROUP_FIXED, "name": "Rent"},
    ).json()
    today = date.today()
    start = today - timedelta(days=40)
    end = today - timedelta(days=10)
    client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=headers,
        json={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "budgets": [{"subcategory_id": rent["id"], "amount": "120.00"}],
        },
    )
    next_start = end + timedelta(days=1)
    next_end = next_start + timedelta(days=29)
    copied = client.post(
        f"/api/families/{family_id}/budget-periods/copy",
        headers=headers,
        json={
            "start_date": next_start.isoformat(),
            "end_date": next_end.isoformat(),
        },
    )
    assert copied.status_code == 201, copied.text
    lines = [l for g in copied.json()["groups"] for l in g["lines"]]
    assert any(l["subcategory_id"] == rent["id"] and l["amount"] == "120.00" for l in lines)


def test_income_excluded_from_spend(client: TestClient) -> None:
    headers = auth_headers(client, "budget-income@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Income Family", "timezone": "UTC"},
    ).json()["id"]
    salary = client.post(
        f"/api/families/{family_id}/budget-subcategories",
        headers=headers,
        json={"group": GROUP_INCOME, "name": "Salary"},
    ).json()
    groceries = next(
        s
        for g in client.get(f"/api/families/{family_id}/budget-subcategories", headers=headers).json()["groups"]
        if g["group"] == GROUP_FIXED
        for s in g["subcategories"]
        if s["role"] == "groceries"
    )
    client.post(
        f"/api/families/{family_id}/expenses",
        headers=headers,
        json={"amount": "2000.00", "subcategory_id": salary["id"]},
    )
    client.post(
        f"/api/families/{family_id}/expenses",
        headers=headers,
        json={"amount": "50.00", "subcategory_id": groceries["id"]},
    )
    spend = client.get(f"/api/families/{family_id}/spend", headers=headers).json()
    current = next(m for m in spend["months"] if m["month"] == spend["current_month"])
    assert current["total"] == "50.00"


def test_overall_budget_summary_from_outflows(db_session: Session) -> None:
    family, user, groceries = _seed_family_with_groceries(db_session)
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
        Budget(period_id=period.id, subcategory_id=groceries.id, amount=Decimal("600.00"))
    )
    db_session.commit()

    summary = budget_service.overall_budget_summary(db_session, family)
    assert summary is not None
    assert summary.amount == Decimal("600.00")
    assert summary.used == Decimal("0.00")
    assert summary.state == "ok"
