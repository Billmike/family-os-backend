from fastapi.testclient import TestClient

from app.models.budget_group import GROUP_FIXED, GROUP_VARIABLE, ROLE_GROCERIES
from tests.conftest import auth_headers


def test_list_seeds_defaults(client: TestClient) -> None:
    headers = auth_headers(client, "subcat-seed@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Sub Family", "timezone": "UTC"},
    ).json()["id"]
    res = client.get(f"/api/families/{family_id}/budget-subcategories", headers=headers)
    assert res.status_code == 200
    groups = res.json()["groups"]
    assert len(groups) == 6
    fixed = next(g for g in groups if g["group"] == GROUP_FIXED)
    names = {s["name"] for s in fixed["subcategories"]}
    assert "Groceries" in names
    groceries = next(s for s in fixed["subcategories"] if s["role"] == ROLE_GROCERIES)
    assert groceries["name"] == "Groceries"


def test_create_rename_archive(client: TestClient) -> None:
    headers = auth_headers(client, "subcat-crud@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "CRUD Family", "timezone": "UTC"},
    ).json()["id"]
    created = client.post(
        f"/api/families/{family_id}/budget-subcategories",
        headers=headers,
        json={"group": GROUP_VARIABLE, "name": "Coffee"},
    )
    assert created.status_code == 201, created.text
    sub_id = created.json()["id"]

    patched = client.patch(
        f"/api/budget-subcategories/{sub_id}",
        headers=headers,
        json={"name": "Cafe"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Cafe"

    deleted = client.delete(f"/api/budget-subcategories/{sub_id}", headers=headers)
    assert deleted.status_code == 204

    listed = client.get(f"/api/families/{family_id}/budget-subcategories", headers=headers).json()
    variable = next(g for g in listed["groups"] if g["group"] == GROUP_VARIABLE)
    assert all(s["name"] != "Cafe" for s in variable["subcategories"])


def test_cannot_archive_groceries(client: TestClient) -> None:
    headers = auth_headers(client, "subcat-groceries@example.com", name="Owner")
    family_id = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Groc Family", "timezone": "UTC"},
    ).json()["id"]
    listed = client.get(f"/api/families/{family_id}/budget-subcategories", headers=headers).json()
    groceries = next(
        s for g in listed["groups"] for s in g["subcategories"] if s["role"] == ROLE_GROCERIES
    )
    res = client.delete(f"/api/budget-subcategories/{groceries['id']}", headers=headers)
    assert res.status_code == 400
