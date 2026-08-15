from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_family_member
from app.models.family import FamilyMember
from app.schemas.notification import DashboardOut
from app.services import dashboard as dashboard_service
from app.services import family as family_service

router = APIRouter(tags=["dashboard"])


@router.get("/api/families/{family_id}/dashboard", response_model=DashboardOut)
def dashboard(
    family_id: UUID,
    member: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> DashboardOut:
    family = family_service.get_family(db, family_id)
    return dashboard_service.get_dashboard(db, family, member)
