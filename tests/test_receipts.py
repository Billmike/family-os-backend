"""Tests for receipt upload, extraction, confirm, and access control."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services.receipt_extraction import ExtractedReceipt, ExtractedReceiptItem
from tests.conftest import auth_headers

# Minimal valid JPEG (1x1 pixel)
JPEG_BYTES = bytes(
    [
        0xFF,
        0xD8,
        0xFF,
        0xE0,
        0x00,
        0x10,
        0x4A,
        0x46,
        0x49,
        0x46,
        0x00,
        0x01,
        0x01,
        0x00,
        0x00,
        0x01,
        0x00,
        0x01,
        0x00,
        0x00,
        0xFF,
        0xDB,
        0x00,
        0x43,
        0x00,
        0x08,
        0x06,
        0x06,
        0x07,
        0x06,
        0x05,
        0x08,
        0x07,
        0x07,
        0x07,
        0x09,
        0x09,
        0x08,
        0x0A,
        0x0C,
        0x14,
        0x0D,
        0x0C,
        0x0B,
        0x0B,
        0x0C,
        0x19,
        0x12,
        0x13,
        0x0F,
        0x14,
        0x1D,
        0x1A,
        0x1F,
        0x1E,
        0x1D,
        0x1A,
        0x1C,
        0x1C,
        0x20,
        0x24,
        0x2E,
        0x27,
        0x20,
        0x22,
        0x2C,
        0x23,
        0x1C,
        0x1C,
        0x28,
        0x37,
        0x29,
        0x2C,
        0x30,
        0x31,
        0x34,
        0x34,
        0x34,
        0x1F,
        0x27,
        0x39,
        0x3D,
        0x38,
        0x32,
        0x3C,
        0x2E,
        0x33,
        0x34,
        0x32,
        0xFF,
        0xC0,
        0x00,
        0x0B,
        0x08,
        0x00,
        0x01,
        0x00,
        0x01,
        0x01,
        0x01,
        0x11,
        0x00,
        0xFF,
        0xC4,
        0x00,
        0x14,
        0x00,
        0x01,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x08,
        0xFF,
        0xC4,
        0x00,
        0x14,
        0x10,
        0x01,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0x00,
        0xFF,
        0xDA,
        0x00,
        0x08,
        0x01,
        0x01,
        0x00,
        0x00,
        0x3F,
        0x00,
        0x7F,
        0xFF,
        0xD9,
    ]
)


def _fake_extraction(**_kwargs) -> ExtractedReceipt:
    return ExtractedReceipt(
        merchant="REWE",
        purchased_at=datetime(2026, 8, 22, 14, 36, 56, tzinfo=timezone.utc),
        currency="EUR",
        subtotal=Decimal("47.33"),
        tax_total=Decimal("4.77"),
        total=Decimal("52.10"),
        suggested_category="Shopping",
        items=[
            ExtractedReceiptItem(
                name="PILZ CHAMP.BRAUN",
                quantity=Decimal("0.142"),
                unit="kg",
                unit_price=Decimal("6.90"),
                total_price=Decimal("0.98"),
                tax_code="B",
            ),
            ExtractedReceiptItem(
                name="OLIVENOEL",
                quantity=Decimal("2"),
                unit="Stk",
                unit_price=Decimal("5.99"),
                total_price=Decimal("11.98"),
                tax_code="B",
            ),
            ExtractedReceiptItem(
                name="SARDINEN",
                quantity=Decimal("5"),
                unit="Stk",
                unit_price=Decimal("1.99"),
                total_price=Decimal("9.95"),
                tax_code="B",
            ),
        ],
        model_name="test-model",
        raw_response={"merchant": "REWE", "total": 52.10},
    )


@pytest.fixture()
def receipt_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    storage = tmp_path / "receipts"
    storage.mkdir()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("RECEIPT_STORAGE_DIR", str(storage))
    monkeypatch.setenv("RECEIPT_SCANNING_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.services.receipt_extraction.extract_receipt",
        _fake_extraction,
    )
    yield storage
    get_settings.cache_clear()


def _create_family(client: TestClient, headers: dict) -> str:
    res = client.post(
        "/api/families",
        headers=headers,
        json={"name": "Receipt Family", "timezone": "UTC"},
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


def _upload(
    client: TestClient,
    headers: dict,
    family_id: str,
    content: bytes = JPEG_BYTES,
    filename: str = "r.jpg",
):
    return client.post(
        f"/api/families/{family_id}/receipts",
        headers=headers,
        files={"file": (filename, io.BytesIO(content), "image/jpeg")},
    )


def test_rejects_non_image(client: TestClient, receipt_env: Path) -> None:
    headers = auth_headers(client, "reject-mime@example.com")
    family_id = _create_family(client, headers)
    res = client.post(
        f"/api/families/{family_id}/receipts",
        headers=headers,
        files={"file": ("x.txt", io.BytesIO(b"not-an-image"), "text/plain")},
    )
    assert res.status_code == 400
    assert res.json()["code"] == "unsupported_media"


def test_rejects_oversized(client: TestClient, receipt_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RECEIPT_MAX_BYTES", "100")
    get_settings.cache_clear()
    headers = auth_headers(client, "reject-size@example.com")
    family_id = _create_family(client, headers)
    big = JPEG_BYTES + (b"\x00" * 200)
    res = _upload(client, headers, family_id, content=big)
    assert res.status_code == 400
    assert res.json()["code"] == "file_too_large"
    get_settings.cache_clear()


def test_upload_extracts_and_confirm(client: TestClient, receipt_env: Path) -> None:
    headers = auth_headers(client, "receipt-ok@example.com")
    family_id = _create_family(client, headers)

    upload = _upload(client, headers, family_id)
    assert upload.status_code == 202, upload.text
    receipt = upload.json()
    assert receipt["status"] in ("processing", "ready")
    receipt_id = receipt["id"]

    polled = client.get(f"/api/receipts/{receipt_id}", headers=headers)
    assert polled.status_code == 200
    data = polled.json()
    assert data["status"] == "ready"
    assert data["merchant"] == "REWE"
    assert float(data["total"]) == 52.10
    assert len(data["items"]) == 3
    assert data["suggested_category"] == "Shopping"

    confirm = client.post(
        f"/api/receipts/{receipt_id}/confirm",
        headers=headers,
        json={
            "category": "Shopping",
            "merchant": "REWE",
            "total": "52.10",
            "currency": "EUR",
            "occurred_at": "2026-08-22T14:36:56Z",
            "note": "Weekly shop",
            "items": [
                {
                    "name": item["name"],
                    "quantity": item["quantity"],
                    "unit": item["unit"],
                    "unit_price": item["unit_price"],
                    "total_price": item["total_price"],
                    "tax_code": item["tax_code"],
                    "is_included": True,
                }
                for item in data["items"]
            ],
        },
    )
    assert confirm.status_code == 200, confirm.text
    expense = confirm.json()
    assert expense["source_type"] == "shopping_session"
    assert expense["source_id"] is not None
    assert expense["source_id"] != receipt_id
    assert float(expense["amount"]) == 52.10
    assert expense["source_item_count"] == 3
    assert expense["category"] == "Shopping"
    assert expense["merchant"] == "REWE"
    assert expense["note"] == "Weekly shop"

    sessions = client.get(f"/api/families/{family_id}/shopping-sessions", headers=headers)
    assert sessions.status_code == 200
    assert len(sessions.json()) >= 1
    trip = sessions.json()[0]
    assert trip["item_count"] == 3
    assert float(trip["total_cost"]) == 52.10
    assert str(trip["id"]) == expense["source_id"]

    again = client.post(
        f"/api/receipts/{receipt_id}/confirm",
        headers=headers,
        json={
            "category": "Shopping",
            "merchant": "REWE",
            "total": "52.10",
            "currency": "EUR",
            "items": [],
        },
    )
    assert again.status_code == 200
    assert again.json()["id"] == expense["id"]

    patch = client.patch(
        f"/api/expenses/{expense['id']}",
        headers=headers,
        json={"note": "Updated note"},
    )
    assert patch.status_code == 400

    linked = client.get(f"/api/expenses/{expense['id']}/receipt", headers=headers)
    assert linked.status_code == 200
    assert linked.json()["id"] == receipt_id
    assert linked.json()["shopping_session_id"] == expense["source_id"]


def test_confirm_non_shopping_receipt_stays_receipt_source(
    client: TestClient,
    receipt_env: Path,
) -> None:
    headers = auth_headers(client, "receipt-transport@example.com")
    family_id = _create_family(client, headers)
    upload = _upload(client, headers, family_id)
    receipt_id = upload.json()["id"]
    polled = client.get(f"/api/receipts/{receipt_id}", headers=headers).json()

    confirm = client.post(
        f"/api/receipts/{receipt_id}/confirm",
        headers=headers,
        json={
            "category": "Transportation",
            "merchant": "REWE",
            "total": "52.10",
            "currency": "EUR",
            "occurred_at": "2026-08-22T14:36:56Z",
            "items": [
                {
                    "name": item["name"],
                    "quantity": item["quantity"],
                    "unit": item["unit"],
                    "unit_price": item["unit_price"],
                    "total_price": item["total_price"],
                    "tax_code": item["tax_code"],
                    "is_included": True,
                }
                for item in polled["items"]
            ],
        },
    )
    assert confirm.status_code == 200, confirm.text
    expense = confirm.json()
    assert expense["source_type"] == "receipt"
    assert expense["source_id"] == receipt_id
    assert expense["category"] == "Transportation"

    linked = client.get(f"/api/receipts/{receipt_id}", headers=headers).json()
    assert linked["shopping_session_id"] is None

    sessions = client.get(f"/api/families/{family_id}/shopping-sessions", headers=headers)
    assert sessions.status_code == 200
    assert sessions.json() == []


def test_extraction_failure(client: TestClient, receipt_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(**_kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr("app.services.receipt_extraction.extract_receipt", boom)
    headers = auth_headers(client, "receipt-fail@example.com")
    family_id = _create_family(client, headers)
    upload = _upload(client, headers, family_id)
    assert upload.status_code == 202
    receipt_id = upload.json()["id"]
    polled = client.get(f"/api/receipts/{receipt_id}", headers=headers)
    assert polled.status_code == 200
    assert polled.json()["status"] == "failed"
    assert "model unavailable" in (polled.json()["error_message"] or "")


def test_discard_removes_file(client: TestClient, receipt_env: Path) -> None:
    headers = auth_headers(client, "receipt-discard@example.com")
    family_id = _create_family(client, headers)
    upload = _upload(client, headers, family_id)
    receipt_id = upload.json()["id"]
    assert any(p.is_file() for p in receipt_env.rglob("*"))

    deleted = client.delete(f"/api/receipts/{receipt_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/receipts/{receipt_id}", headers=headers).status_code == 404
    assert not any(p.is_file() for p in receipt_env.rglob("*"))


def test_cross_family_access_forbidden(client: TestClient, receipt_env: Path) -> None:
    owner = auth_headers(client, "receipt-owner@example.com")
    other = auth_headers(client, "receipt-other@example.com")
    family_id = _create_family(client, owner)
    upload = _upload(client, owner, family_id)
    receipt_id = upload.json()["id"]

    res = client.get(f"/api/receipts/{receipt_id}", headers=other)
    # Membership is obscured as 404 (same as other family-scoped resources)
    assert res.status_code == 404


def test_unavailable_without_api_key(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("RECEIPT_STORAGE_DIR", str(tmp_path / "r"))
    get_settings.cache_clear()
    headers = auth_headers(client, "receipt-no-key@example.com")
    family_id = _create_family(client, headers)
    res = _upload(client, headers, family_id)
    assert res.status_code == 503
    assert res.json()["code"] == "receipt_scanning_unavailable"
    get_settings.cache_clear()
