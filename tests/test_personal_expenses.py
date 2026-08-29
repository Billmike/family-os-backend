from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.personal_expense import PersonalExpenseAccount
from tests.conftest import auth_headers


def _create_family(client: TestClient, headers: dict, name: str = "Money Family") -> str:
    family = client.post(
        "/api/families",
        headers=headers,
        json={"name": name, "timezone": "UTC"},
    )
    assert family.status_code == 200, family.text
    return family.json()["id"]


def _invite_partner(client: TestClient, owner: dict, family_id: str, email: str) -> dict:
    token = client.post(
        f"/api/families/{family_id}/invitations",
        headers=owner,
        json={},
    ).json()["invite_token"]
    partner = auth_headers(client, email, name="Partner")
    accepted = client.post(f"/api/invitations/{token}/accept", headers=partner)
    assert accepted.status_code == 200, accepted.text
    return partner


def test_create_family_sets_user_timezone(client: TestClient) -> None:
    headers = auth_headers(client, "tz-owner@example.com", name="Owner")
    before = client.get("/api/auth/me", headers=headers)
    assert before.status_code == 200
    assert before.json()["timezone"] is None

    client.post(
        "/api/families",
        headers=headers,
        json={"name": "Berlin Family", "timezone": "Europe/Berlin"},
    )
    me = client.get("/api/auth/me", headers=headers)
    assert me.json()["timezone"] == "Europe/Berlin"


def test_list_accounts_does_not_create_default(client: TestClient, db_session: Session) -> None:
    headers = auth_headers(client, "empty-accounts@example.com", name="Owner")
    listed = client.get("/api/me/expense-accounts", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["accounts"] == []
    assert body["current_month_count"] == 0
    assert float(body["current_month_total"]) == 0.0
    assert db_session.query(PersonalExpenseAccount).count() == 0


def test_account_crud_and_duplicate_name(client: TestClient) -> None:
    headers = auth_headers(client, "acct-owner@example.com", name="Owner")
    _create_family(client, headers)

    created = client.post(
        "/api/me/expense-accounts",
        headers=headers,
        json={"name": "Coffee money", "timezone": "UTC"},
    )
    assert created.status_code == 200, created.text
    account = created.json()
    assert account["name"] == "Coffee money"
    assert account["currency"] == "EUR"
    assert float(account["current_month_total"]) == 0.0

    dup = client.post(
        "/api/me/expense-accounts",
        headers=headers,
        json={"name": "Coffee money"},
    )
    assert dup.status_code == 409

    renamed = client.patch(
        f"/api/me/expense-accounts/{account['id']}",
        headers=headers,
        json={"name": "Side cash"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Side cash"

    listed = client.get("/api/me/expense-accounts", headers=headers)
    assert len(listed.json()["accounts"]) == 1

    deleted = client.delete(f"/api/me/expense-accounts/{account['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/me/expense-accounts", headers=headers).json()["accounts"] == []


def test_personal_expense_crud_and_invalid_category(client: TestClient) -> None:
    headers = auth_headers(client, "pex-owner@example.com", name="Owner")
    _create_family(client, headers)
    account_id = client.post(
        "/api/me/expense-accounts",
        headers=headers,
        json={"name": "Personal"},
    ).json()["id"]

    bad = client.post(
        f"/api/me/expense-accounts/{account_id}/expenses",
        headers=headers,
        json={"amount": "12.50", "category": "NotACategory"},
    )
    assert bad.status_code == 422

    created = client.post(
        f"/api/me/expense-accounts/{account_id}/expenses",
        headers=headers,
        json={
            "amount": "12.50",
            "category": "Dining",
            "merchant": "Café",
            "note": "Lunch",
        },
    )
    assert created.status_code == 200, created.text
    expense = created.json()
    assert expense["category"] == "Dining"
    assert expense["merchant"] == "Café"
    assert float(expense["amount"]) == 12.50

    month = client.get("/api/me/expense-accounts", headers=headers).json()["current_month"]
    listed = client.get(
        f"/api/me/expense-accounts/{account_id}/expenses?month={month}",
        headers=headers,
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    summary = client.get("/api/me/expense-accounts", headers=headers).json()
    assert summary["current_month_count"] == 1
    assert float(summary["current_month_total"]) == 12.50
    assert float(summary["accounts"][0]["current_month_total"]) == 12.50

    patched = client.patch(
        f"/api/personal-expenses/{expense['id']}",
        headers=headers,
        json={"amount": "15.00", "merchant": "Café Neun"},
    )
    assert patched.status_code == 200
    assert float(patched.json()["amount"]) == 15.00
    assert patched.json()["merchant"] == "Café Neun"

    deleted = client.delete(f"/api/personal-expenses/{expense['id']}", headers=headers)
    assert deleted.status_code == 204
    listed_after = client.get(
        f"/api/me/expense-accounts/{account_id}/expenses?month={month}",
        headers=headers,
    )
    assert listed_after.json() == []


def test_partner_and_owner_cannot_see_each_others_accounts(client: TestClient) -> None:
    owner = auth_headers(client, "iso-owner@example.com", name="Owner")
    family_id = _create_family(client, owner, "Shared Family")
    partner = _invite_partner(client, owner, family_id, "iso-partner@example.com")

    owner_acct = client.post(
        "/api/me/expense-accounts",
        headers=owner,
        json={"name": "Owner cash"},
    ).json()
    expense = client.post(
        f"/api/me/expense-accounts/{owner_acct['id']}/expenses",
        headers=owner,
        json={"amount": "20.00", "category": "Transport"},
    ).json()

    partner_list = client.get("/api/me/expense-accounts", headers=partner)
    assert partner_list.json()["accounts"] == []

    assert client.get(
        f"/api/me/expense-accounts/{owner_acct['id']}/expenses?month=2026-08",
        headers=partner,
    ).status_code == 404
    assert client.patch(
        f"/api/me/expense-accounts/{owner_acct['id']}",
        headers=partner,
        json={"name": "Stolen"},
    ).status_code == 404
    assert client.delete(
        f"/api/me/expense-accounts/{owner_acct['id']}",
        headers=partner,
    ).status_code == 404
    assert client.patch(
        f"/api/personal-expenses/{expense['id']}",
        headers=partner,
        json={"amount": "1.00"},
    ).status_code == 404
    assert client.delete(
        f"/api/personal-expenses/{expense['id']}",
        headers=partner,
    ).status_code == 404

    missing = uuid4()
    assert client.get(
        f"/api/me/expense-accounts/{missing}/expenses?month=2026-08",
        headers=owner,
    ).status_code == 404


def test_personal_expense_does_not_change_family_spend_or_budget(client: TestClient) -> None:
    headers = auth_headers(client, "ledger-split@example.com", name="Owner")
    family_id = _create_family(client, headers, "Split Family")

    spend_before = client.get(f"/api/families/{family_id}/spend?months=3", headers=headers)
    assert spend_before.status_code == 200
    before_total = float(spend_before.json()["months"][-1]["total"])
    before_count = spend_before.json()["months"][-1]["entry_count"]

    today = date.today()
    period = client.post(
        f"/api/families/{family_id}/budget-periods",
        headers=headers,
        json={
            "start_date": today.replace(day=1).isoformat(),
            "end_date": today.isoformat(),
            "budgets": [],
        },
    )
    assert period.status_code == 201, period.text
    actual_before = period.json()["summary"]["total_expenses_actual"]

    account_id = client.post(
        "/api/me/expense-accounts",
        headers=headers,
        json={"name": "Private"},
    ).json()["id"]
    created = client.post(
        f"/api/me/expense-accounts/{account_id}/expenses",
        headers=headers,
        json={"amount": "99.00", "category": "Shopping"},
    )
    assert created.status_code == 200

    spend_after = client.get(f"/api/families/{family_id}/spend?months=3", headers=headers)
    assert float(spend_after.json()["months"][-1]["total"]) == before_total
    assert spend_after.json()["months"][-1]["entry_count"] == before_count

    current = client.get(f"/api/families/{family_id}/budget-periods/current", headers=headers)
    assert current.status_code == 200
    assert current.json()["summary"]["total_expenses_actual"] == actual_before


def test_accounts_survive_leaving_family(client: TestClient) -> None:
    owner = auth_headers(client, "leave-pex@example.com", name="Owner")
    family_id = _create_family(client, owner, "Leave Family")
    partner = _invite_partner(client, owner, family_id, "leave-pex-partner@example.com")

    account_id = client.post(
        "/api/me/expense-accounts",
        headers=partner,
        json={"name": "Partner wallet"},
    ).json()["id"]
    client.post(
        f"/api/me/expense-accounts/{account_id}/expenses",
        headers=partner,
        json={"amount": "7.00", "category": "Other"},
    )

    leave = client.post(f"/api/families/{family_id}/leave", headers=partner)
    assert leave.status_code == 204

    listed = client.get("/api/me/expense-accounts", headers=partner)
    assert listed.status_code == 200
    names = [row["name"] for row in listed.json()["accounts"]]
    assert names == ["Partner wallet"]
    assert listed.json()["current_month_count"] == 1
