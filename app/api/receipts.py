from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.expense import ExpenseOut
from app.schemas.receipt import ReceiptConfirm, ReceiptOut
from app.services import expense as expense_service
from app.services import family as family_service
from app.services import receipt as receipt_service
from app.services import receipt_storage

router = APIRouter(tags=["receipts"])


@router.post(
    "/api/families/{family_id}/receipts",
    response_model=ReceiptOut,
    status_code=202,
)
def upload_receipt(
    family_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category_hint: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> ReceiptOut:
    family = family_service.get_family(db, family_id)
    hint = category_hint.strip() if category_hint else None
    out = receipt_service.create_receipt(db, family, user, file, category_hint=hint or None)
    background_tasks.add_task(receipt_service.run_extraction, out.id)
    return out


@router.get("/api/families/{family_id}/receipts", response_model=list[ReceiptOut])
def list_family_receipts(
    family_id: UUID,
    status: str | None = Query(default=None),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> list[ReceiptOut]:
    family = family_service.get_family(db, family_id)
    return receipt_service.list_receipts(db, family, status=status)


@router.get("/api/receipts/{receipt_id}", response_model=ReceiptOut)
def get_receipt(
    receipt_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReceiptOut:
    receipt = receipt_service.get_receipt(db, receipt_id)
    get_membership(db, receipt.family_id, user.id)
    return receipt_service.receipt_to_out(receipt)


@router.get("/api/receipts/{receipt_id}/image")
def get_receipt_image(
    receipt_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    receipt = receipt_service.get_receipt(db, receipt_id)
    get_membership(db, receipt.family_id, user.id)
    path = receipt_storage.absolute_path(receipt.storage_key)
    return FileResponse(
        path,
        media_type=receipt.mime_type,
        filename=receipt.original_filename or path.name,
    )


@router.post("/api/receipts/{receipt_id}/confirm", response_model=ExpenseOut)
def confirm_receipt(
    receipt_id: UUID,
    data: ReceiptConfirm,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExpenseOut:
    receipt = receipt_service.get_receipt(db, receipt_id)
    get_membership(db, receipt.family_id, user.id)
    return receipt_service.confirm_receipt(db, receipt, user, data)


@router.delete("/api/receipts/{receipt_id}", status_code=204)
def discard_receipt(
    receipt_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    receipt = receipt_service.get_receipt(db, receipt_id)
    get_membership(db, receipt.family_id, user.id)
    receipt_service.discard_receipt(db, receipt)
    return Response(status_code=204)


@router.get("/api/expenses/{expense_id}/receipt", response_model=ReceiptOut)
def get_expense_receipt(
    expense_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReceiptOut:
    expense = expense_service.get_expense(db, expense_id)
    get_membership(db, expense.family_id, user.id)
    return receipt_service.get_receipt_for_expense(db, expense)
