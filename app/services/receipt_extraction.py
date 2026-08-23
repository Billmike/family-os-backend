from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.exceptions import bad_request
from app.models.expense import EXPENSE_CATEGORIES

_MONEY = Decimal("0.01")
_TOLERANCE = Decimal("0.02")

ExpenseCategoryLiteral = Literal[
    "Shopping",
    "Transportation",
    "Housing",
    "Utilities",
    "Dining",
    "Health",
    "Childcare",
    "Other",
]

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "merchant": {"type": ["string", "null"]},
        "purchased_at": {
            "type": ["string", "null"],
            "description": "ISO-8601 datetime of the purchase when present on the receipt",
        },
        "currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "subtotal": {"type": ["number", "null"]},
        "tax_total": {"type": ["number", "null"]},
        "total": {"type": "number"},
        "suggested_category": {
            "type": "string",
            "enum": list(EXPENSE_CATEGORIES),
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": ["number", "null"]},
                    "unit": {"type": ["string", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "total_price": {"type": "number"},
                    "tax_code": {"type": ["string", "null"]},
                },
                "required": ["name", "quantity", "unit", "unit_price", "total_price", "tax_code"],
            },
        },
    },
    "required": [
        "merchant",
        "purchased_at",
        "currency",
        "subtotal",
        "tax_total",
        "total",
        "suggested_category",
        "items",
    ],
}

SYSTEM_PROMPT = """You extract structured data from grocery and retail receipt photos.
Return only data that is clearly visible. Prefer the printed SUMME / TOTAL / Gesamtbetrag as the total.
Never invent line items. Currency is usually EUR for German receipts.

German receipt conventions (REWE and similar):
- Decimal comma: 1,99 means 1.99
- SUMME is the gross total paid
- Letters A and B next to prices are VAT classes (e.g. 19% / 7%), not prices
- Weight lines like "0,142 kg x 6,90 EUR/kg" are one item: quantity=0.142, unit=kg, unit_price=6.90, total_price=line total
- Multiplier lines like "2 Stk x 5,99" are one item: quantity=2, unit=Stk (or piece), unit_price=5.99
- "Datum: DD.MM.YYYY" (and optional time) is the purchase date; return ISO-8601 with timezone if known, else date only as YYYY-MM-DDT00:00:00
- Prefer merchant from store name / brand (e.g. REWE), not the address alone

suggested_category must be one of: Shopping, Transportation, Housing, Utilities, Dining, Health, Childcare, Other.
Grocery / supermarket receipts are Shopping. Baby products may still be Shopping unless clearly Childcare-only."""


class ExtractedReceiptItem(BaseModel):
    name: str
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    total_price: Decimal
    tax_code: str | None = None


class ExtractedReceipt(BaseModel):
    merchant: str | None = None
    purchased_at: datetime | None = None
    currency: str = "EUR"
    subtotal: Decimal | None = None
    tax_total: Decimal | None = None
    total: Decimal
    suggested_category: ExpenseCategoryLiteral = "Shopping"
    items: list[ExtractedReceiptItem] = Field(default_factory=list)
    model_name: str | None = None
    raw_response: dict[str, Any] | None = None


def _as_money(value: Decimal | float | int | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(_MONEY, rounding=ROUND_HALF_UP)


def validate_totals(extracted: ExtractedReceipt) -> bool:
    """Return True when item sum and printed total differ by more than tolerance."""
    printed = _as_money(extracted.total)
    if printed is None:
        return True
    item_sum = sum((_as_money(item.total_price) or Decimal("0.00")) for item in extracted.items)
    return abs(item_sum - printed) > _TOLERANCE


def extract_receipt(
    *,
    image_bytes: bytes,
    mime_type: str,
    category_hint: str | None = None,
) -> ExtractedReceipt:
    settings = get_settings()
    if not settings.openai_api_key:
        raise bad_request("OpenAI API key is not configured", code="receipt_scanning_unavailable")

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    import base64

    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"

    user_text = "Extract all purchase line items, merchant, date, currency, tax totals, and the printed total."
    if category_hint:
        user_text += f" The user hinted the category may be: {category_hint}."

    response = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "receipt_extraction",
                "strict": True,
                "schema": EXTRACTION_SCHEMA,
            },
        },
        temperature=0,
    )

    content = response.choices[0].message.content
    if not content:
        raise bad_request("Empty extraction response", code="extraction_failed")

    import json

    raw = json.loads(content)
    purchased_at = raw.get("purchased_at")
    parsed_purchased_at: datetime | None = None
    if purchased_at:
        try:
            parsed_purchased_at = datetime.fromisoformat(str(purchased_at).replace("Z", "+00:00"))
        except ValueError:
            parsed_purchased_at = None

    items = [
        ExtractedReceiptItem(
            name=str(item.get("name") or "").strip() or "Item",
            quantity=_as_money(item.get("quantity")) if item.get("quantity") is not None else None,
            unit=(str(item["unit"]).strip() if item.get("unit") else None),
            unit_price=_as_money(item.get("unit_price")),
            total_price=_as_money(item.get("total_price")) or Decimal("0.00"),
            tax_code=(str(item["tax_code"]).strip() if item.get("tax_code") else None),
        )
        for item in (raw.get("items") or [])
    ]

    category = raw.get("suggested_category") or "Shopping"
    if category not in EXPENSE_CATEGORIES:
        category = "Shopping"

    return ExtractedReceipt(
        merchant=(str(raw["merchant"]).strip() if raw.get("merchant") else None),
        purchased_at=parsed_purchased_at,
        currency=str(raw.get("currency") or "EUR").strip().upper()[:3],
        subtotal=_as_money(raw.get("subtotal")),
        tax_total=_as_money(raw.get("tax_total")),
        total=_as_money(raw.get("total")) or Decimal("0.00"),
        suggested_category=category,
        items=items,
        model_name=settings.openai_model,
        raw_response=raw,
    )
