import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import bad_request, not_found, service_unavailable
from app.models.expense import SOURCE_RECEIPT, Expense
from app.models.family import Family
from app.models.receipt import (
    STATUS_CONFIRMED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_READY,
    Receipt,
    ReceiptItem,
)
from app.models.user import User
from app.realtime.hub import hub
from app.schemas.expense import ExpenseOut
from app.schemas.receipt import ReceiptConfirm, ReceiptItemOut, ReceiptOut
from app.services import budget as budget_service
from app.services import budget_subcategory as subcategory_service
from app.services import expense as expense_service
from app.services import receipt_extraction
from app.services import receipt_storage
from app.services import shopping_session as shopping_session_service
from app.models.budget_group import ROLE_GROCERIES

logger = logging.getLogger(__name__)

_MONEY = Decimal("0.01")


def _as_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(_MONEY, rounding=ROUND_HALF_UP)


def receipt_to_out(receipt: Receipt, *, suggested_subcategory_id: UUID | None = None) -> ReceiptOut:
    items = sorted(receipt.items, key=lambda item: item.position)
    return ReceiptOut(
        id=receipt.id,
        family_id=receipt.family_id,
        uploaded_by=receipt.uploaded_by,
        status=receipt.status,
        mime_type=receipt.mime_type,
        byte_size=receipt.byte_size,
        original_filename=receipt.original_filename,
        category_hint=receipt.category_hint,
        suggested_category=receipt.suggested_category,
        suggested_subcategory_id=suggested_subcategory_id,
        merchant=receipt.merchant,
        purchased_at=receipt.purchased_at,
        currency=receipt.currency,
        subtotal=_as_money(receipt.subtotal),
        tax_total=_as_money(receipt.tax_total),
        total=_as_money(receipt.total),
        totals_mismatch=bool(receipt.totals_mismatch),
        model_name=receipt.model_name,
        error_message=receipt.error_message,
        expense_id=receipt.expense_id,
        shopping_session_id=receipt.shopping_session_id,
        items=[
            ReceiptItemOut(
                id=item.id,
                receipt_id=item.receipt_id,
                position=item.position,
                name=item.name,
                quantity=_as_money(item.quantity) if item.quantity is not None else None,
                unit=item.unit,
                unit_price=_as_money(item.unit_price),
                total_price=_as_money(item.total_price) or Decimal("0.00"),
                tax_code=item.tax_code,
                is_included=bool(item.is_included),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ],
        created_at=receipt.created_at,
        updated_at=receipt.updated_at,
    )


def _resolve_suggested_subcategory_id(db: Session, receipt: Receipt) -> UUID | None:
    if not receipt.suggested_category:
        return None
    try:
        sub = subcategory_service.subcategory_for_legacy_category(
            db, receipt.family_id, receipt.suggested_category
        )
        return sub.id
    except Exception:  # noqa: BLE001
        return None


def receipt_to_out_resolved(db: Session, receipt: Receipt) -> ReceiptOut:
    return receipt_to_out(
        receipt,
        suggested_subcategory_id=_resolve_suggested_subcategory_id(db, receipt),
    )


def _broadcast(family_id: UUID, event_type: str, receipt: Receipt, db: Session | None = None) -> None:
    suggested_id = None
    if db is not None:
        suggested_id = _resolve_suggested_subcategory_id(db, receipt)
    hub.broadcast(
        family_id,
        {
            "type": event_type,
            "receipt": receipt_to_out(receipt, suggested_subcategory_id=suggested_id).model_dump(mode="json"),
        },
    )


def get_receipt(db: Session, receipt_id: UUID) -> Receipt:
    receipt = (
        db.query(Receipt)
        .options(joinedload(Receipt.items))
        .filter(Receipt.id == receipt_id)
        .first()
    )
    if receipt is None:
        raise not_found("Receipt not found")
    return receipt


def list_receipts(
    db: Session,
    family: Family,
    *,
    status: str | None = None,
) -> list[ReceiptOut]:
    query = (
        db.query(Receipt)
        .options(joinedload(Receipt.items))
        .filter(Receipt.family_id == family.id)
    )
    if status is not None:
        query = query.filter(Receipt.status == status)
    rows = query.order_by(Receipt.created_at.desc()).all()
    return [receipt_to_out_resolved(db, row) for row in rows]


def get_receipt_for_expense(db: Session, expense: Expense) -> ReceiptOut:
    receipt = (
        db.query(Receipt)
        .options(joinedload(Receipt.items))
        .filter(Receipt.expense_id == expense.id)
        .first()
    )
    if receipt is None:
        raise not_found("No receipt linked to this expense")
    return receipt_to_out_resolved(db, receipt)


def create_receipt(
    db: Session,
    family: Family,
    user: User,
    file: UploadFile,
    *,
    category_hint: str | None = None,
) -> ReceiptOut:
    settings = get_settings()
    if not settings.receipt_scanning_enabled or not settings.openai_api_key:
        raise service_unavailable(
            "Receipt scanning is not configured. Set OPENAI_API_KEY to enable it.",
            code="receipt_scanning_unavailable",
        )

    receipt_id = uuid4()
    storage_key, mime_type, byte_size = receipt_storage.save_upload(
        file, family_id=family.id, receipt_id=receipt_id
    )
    receipt = Receipt(
        id=receipt_id,
        family_id=family.id,
        uploaded_by=user.id,
        status=STATUS_PROCESSING,
        storage_key=storage_key,
        mime_type=mime_type,
        byte_size=byte_size,
        original_filename=file.filename,
        category_hint=category_hint,
        totals_mismatch=False,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt_to_out(receipt)


def run_extraction(receipt_id: UUID) -> None:
    """Background job: open a fresh session, extract, persist items."""
    db = SessionLocal()
    try:
        receipt = (
            db.query(Receipt)
            .options(joinedload(Receipt.items))
            .filter(Receipt.id == receipt_id)
            .first()
        )
        if receipt is None:
            return
        if receipt.status != STATUS_PROCESSING:
            return

        try:
            image_bytes = receipt_storage.read_bytes(receipt.storage_key)
            extracted = receipt_extraction.extract_receipt(
                image_bytes=image_bytes,
                mime_type=receipt.mime_type,
                category_hint=receipt.category_hint,
            )
            mismatch = receipt_extraction.validate_totals(extracted)

            receipt.suggested_category = extracted.suggested_category
            receipt.merchant = extracted.merchant
            receipt.purchased_at = extracted.purchased_at
            receipt.currency = extracted.currency
            receipt.subtotal = extracted.subtotal
            receipt.tax_total = extracted.tax_total
            receipt.total = extracted.total
            receipt.totals_mismatch = mismatch
            receipt.model_name = extracted.model_name
            receipt.raw_response = extracted.raw_response
            receipt.error_message = None
            receipt.status = STATUS_READY
            receipt.updated_at = datetime.now(timezone.utc)

            for existing in list(receipt.items):
                db.delete(existing)
            db.flush()

            for index, item in enumerate(extracted.items):
                db.add(
                    ReceiptItem(
                        receipt_id=receipt.id,
                        position=index,
                        name=item.name[:200],
                        quantity=item.quantity,
                        unit=item.unit,
                        unit_price=item.unit_price,
                        total_price=item.total_price,
                        tax_code=item.tax_code,
                        is_included=True,
                    )
                )
            db.commit()
            db.refresh(receipt)
            receipt = get_receipt(db, receipt.id)
            _broadcast(receipt.family_id, "receipt.ready", receipt, db)
        except Exception as exc:
            logger.exception("Receipt extraction failed for %s", receipt_id)
            db.rollback()
            receipt = db.get(Receipt, receipt_id)
            if receipt is None:
                return
            receipt.status = STATUS_FAILED
            receipt.error_message = str(exc)[:500]
            receipt.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(receipt)
            receipt = get_receipt(db, receipt.id)
            _broadcast(receipt.family_id, "receipt.failed", receipt, db)
    finally:
        db.close()


def confirm_receipt(
    db: Session,
    receipt: Receipt,
    user: User,
    data: ReceiptConfirm,
) -> ExpenseOut:
    if receipt.status == STATUS_CONFIRMED and receipt.expense_id is not None:
        expense = expense_service.get_expense(db, receipt.expense_id)
        counts = expense_service._source_item_counts(db, [expense])
        count = counts.get(expense.source_id) if expense.source_id else None
        sub = subcategory_service.get_subcategory_any(db, expense.subcategory_id)
        return expense_service.expense_to_out(expense, subcategory=sub, source_item_count=count)

    if receipt.status not in (STATUS_READY, STATUS_FAILED):
        if receipt.status == STATUS_PROCESSING:
            raise bad_request("Receipt is still processing", code="receipt_not_ready")
        raise bad_request("Receipt cannot be confirmed in its current state")

    if data.total <= 0:
        raise bad_request("Total must be greater than zero")

    sub = subcategory_service.get_subcategory(db, data.subcategory_id)
    if sub.family_id != receipt.family_id:
        raise bad_request("Invalid budget subcategory")

    # Replace items with the confirmed set
    for existing in list(receipt.items):
        db.delete(existing)
    db.flush()

    for index, item in enumerate(data.items):
        name = (item.name or "").strip()
        if not name:
            continue
        db.add(
            ReceiptItem(
                receipt_id=receipt.id,
                position=index,
                name=name[:200],
                quantity=item.quantity,
                unit=item.unit,
                unit_price=item.unit_price,
                total_price=item.total_price,
                tax_code=item.tax_code,
                is_included=item.is_included,
            )
        )

    occurred_at = data.occurred_at or receipt.purchased_at or datetime.now(timezone.utc)
    is_groceries = sub.role == ROLE_GROCERIES

    if is_groceries:
        db.flush()
        db.refresh(receipt)
        receipt = get_receipt(db, receipt.id)

        session = shopping_session_service.create_completed_session_from_receipt(
            db,
            receipt=receipt,
            user=user,
            data=data,
            items=list(receipt.items),
            occurred_at=occurred_at,
        )
        receipt.shopping_session_id = session.id
        expense = expense_service.record_shopping_session_expense(db, session=session, user=user)
        expense.merchant = data.merchant or receipt.merchant
        expense.note = data.note
        db.flush()

        receipt.status = STATUS_CONFIRMED
        receipt.expense_id = expense.id
        receipt.merchant = data.merchant or receipt.merchant
        receipt.total = data.total
        receipt.currency = data.currency
        receipt.purchased_at = occurred_at
        receipt.suggested_category = receipt.suggested_category or "Shopping"
        receipt.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(expense)
        db.refresh(session)

        session_out = shopping_session_service._session_to_out(session)
        item_count = session_out.item_count
        groceries = subcategory_service.get_subcategory_any(db, expense.subcategory_id)
        out = expense_service.expense_to_out(
            expense, subcategory=groceries, source_item_count=item_count
        )
        hub.broadcast(
            receipt.family_id,
            {
                "type": "shopping.session.completed",
                "session": session_out.model_dump(mode="json"),
            },
        )
        expense_service._broadcast(
            receipt.family_id,
            "expense.created",
            expense,
            subcategory=groceries,
            source_item_count=item_count,
        )
        _broadcast(receipt.family_id, "receipt.ready", get_receipt(db, receipt.id), db)
        budget_service.safe_evaluate_budget_alerts(
            db, receipt.family_id, actor_user_id=user.id, occurred_at=occurred_at
        )
        return out

    expense = Expense(
        family_id=receipt.family_id,
        amount=data.total,
        currency=data.currency,
        subcategory_id=data.subcategory_id,
        merchant=data.merchant or receipt.merchant,
        note=data.note,
        occurred_at=occurred_at,
        created_by=user.id,
        source_type=SOURCE_RECEIPT,
        source_id=receipt.id,
    )
    db.add(expense)
    db.flush()

    receipt.status = STATUS_CONFIRMED
    receipt.expense_id = expense.id
    receipt.merchant = data.merchant or receipt.merchant
    receipt.total = data.total
    receipt.currency = data.currency
    receipt.purchased_at = occurred_at
    receipt.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(expense)
    db.refresh(receipt)

    included_count = sum(1 for item in receipt.items if item.is_included)
    out = expense_service.expense_to_out(
        expense,
        subcategory=sub,
        source_item_count=included_count or len(data.items),
    )
    expense_service._broadcast(
        receipt.family_id,
        "expense.created",
        expense,
        subcategory=sub,
        source_item_count=out.source_item_count,
    )
    _broadcast(receipt.family_id, "receipt.ready", get_receipt(db, receipt.id), db)
    budget_service.safe_evaluate_budget_alerts(
        db, receipt.family_id, actor_user_id=user.id, occurred_at=occurred_at
    )
    return out


def discard_receipt(db: Session, receipt: Receipt) -> None:
    if receipt.status == STATUS_CONFIRMED:
        raise bad_request("Confirmed receipts cannot be discarded; delete the expense instead")
    storage_key = receipt.storage_key
    family_id = receipt.family_id
    receipt_id = receipt.id
    db.delete(receipt)
    db.commit()
    receipt_storage.delete_file(storage_key)
    hub.broadcast(
        family_id,
        {"type": "receipt.deleted", "receipt_id": str(receipt_id)},
    )


def delete_receipt_for_expense(db: Session, expense: Expense) -> None:
    """Called when a receipt-sourced expense is deleted."""
    if expense.source_type != SOURCE_RECEIPT or expense.source_id is None:
        return
    receipt = db.get(Receipt, expense.source_id)
    if receipt is None:
        return
    storage_key = receipt.storage_key
    db.delete(receipt)
    receipt_storage.delete_file(storage_key)
