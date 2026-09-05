from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_family_member
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.assistant import AssistantTurnOut, AssistantTurnRequest
from app.services import assistant as assistant_service

router = APIRouter(tags=["assistant"])


@router.post("/api/families/{family_id}/assistant/turns", response_model=AssistantTurnOut)
def propose_turn(
    family_id: UUID,
    data: AssistantTurnRequest,
    user: User = Depends(get_current_user),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> AssistantTurnOut:
    return assistant_service.run_turn(
        db=db,
        family_id=family_id,
        user=user,
        messages=data.messages,
    )
