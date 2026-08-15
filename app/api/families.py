from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.family import (
    FamilyCreate,
    FamilyOut,
    FamilyUpdate,
    InvitationAcceptOut,
    InvitationCreate,
    InvitationOut,
    MemberCreate,
    MemberOut,
)
from app.services import family as family_service

router = APIRouter(tags=["families"])


@router.post("/api/families", response_model=FamilyOut)
def create_family(
    data: FamilyCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FamilyOut:
    family = family_service.create_family(db, user, data)
    return family_service.family_to_out(family)


@router.get("/api/me/families", response_model=list[FamilyOut])
def my_families(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FamilyOut]:
    return [family_service.family_to_out(f) for f in family_service.list_user_families(db, user.id)]


@router.get("/api/families/{family_id}", response_model=FamilyOut)
def get_family(
    family_id: UUID,
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> FamilyOut:
    family = family_service.get_family(db, family_id)
    return family_service.family_to_out(family)


@router.patch("/api/families/{family_id}", response_model=FamilyOut)
def patch_family(
    family_id: UUID,
    data: FamilyUpdate,
    member: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> FamilyOut:
    family = family_service.get_family(db, family_id)
    family = family_service.update_family(db, family, member, data)
    return family_service.family_to_out(family)


@router.get("/api/families/{family_id}/members", response_model=list[MemberOut])
def get_members(
    family_id: UUID,
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    return [family_service.member_to_out(m) for m in family_service.list_members(db, family_id)]


@router.post("/api/families/{family_id}/members", response_model=MemberOut)
def post_member(
    family_id: UUID,
    data: MemberCreate,
    member: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> MemberOut:
    created = family_service.add_member(db, family_id, member, data)
    return family_service.member_to_out(created)


@router.post("/api/families/{family_id}/invitations", response_model=InvitationOut)
def post_invitation(
    family_id: UUID,
    data: InvitationCreate,
    member: FamilyMember = Depends(require_family_member),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvitationOut:
    family = family_service.get_family(db, family_id)
    return family_service.create_invitation(db, family, member, user, data)


@router.post("/api/invitations/{token}/accept", response_model=InvitationAcceptOut)
def accept_invitation(
    token: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvitationAcceptOut:
    family, member = family_service.accept_invitation(db, token, user)
    return InvitationAcceptOut(
        family=family_service.family_to_out(family),
        member=family_service.member_to_out(member),
    )


@router.post("/api/families/{family_id}/leave", status_code=204)
def leave_family(
    family_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    # Verify membership via helper (404 if not a member)
    get_membership(db, family_id, user.id)
    family_service.leave_family(db, family_id, user)
