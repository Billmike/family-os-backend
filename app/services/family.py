import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import FamilyRole
from app.core.exceptions import bad_request, conflict, forbidden, not_found
from app.models.family import Family, FamilyInvitation, FamilyMember
from app.models.shopping import ShoppingList, ShoppingLocation, DEFAULT_SHOPPING_LOCATIONS
from app.models.user import User
from app.realtime.hub import hub
from app.services import notifications as notification_service
from app.schemas.family import (
    FamilyCreate,
    FamilyOut,
    FamilyUpdate,
    InvitationCreate,
    InvitationOut,
    MemberCreate,
    MemberOut,
)
from app.services.email import try_send_invitation_email

settings = get_settings()

VALID_ROLES = {FamilyRole.OWNER, FamilyRole.PARENT, FamilyRole.CHILD}
LINKED_ADULT_ROLES = (FamilyRole.OWNER, FamilyRole.PARENT)


def seed_default_shopping_locations(db: Session, family_id: UUID) -> None:
    for i, name in enumerate(DEFAULT_SHOPPING_LOCATIONS):
        db.add(ShoppingLocation(family_id=family_id, name=name, sort_order=i))


def _advisory_lock_family(db: Session, family_id: UUID) -> None:
    """Serialize leave (and similar) mutations per family on PostgreSQL."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:fid))"), {"fid": str(family_id)})


def _count_linked_adults(db: Session, family_id: UUID, *, exclude_member_id: UUID | None = None) -> int:
    q = db.query(FamilyMember).filter(
        FamilyMember.family_id == family_id,
        FamilyMember.user_id.isnot(None),
        FamilyMember.role.in_(LINKED_ADULT_ROLES),
    )
    if exclude_member_id is not None:
        q = q.filter(FamilyMember.id != exclude_member_id)
    return q.count()


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_family(db: Session, user: User, data: FamilyCreate) -> Family:
    family = Family(name=data.name.strip(), timezone=data.timezone)
    db.add(family)
    db.flush()
    owner = FamilyMember(
        family_id=family.id,
        user_id=user.id,
        name=user.name,
        role=FamilyRole.OWNER,
        avatar_url=user.avatar_url,
    )
    db.add(owner)
    groceries = ShoppingList(family_id=family.id, name="Groceries")
    db.add(groceries)
    seed_default_shopping_locations(db, family.id)
    db.commit()
    db.refresh(family)
    return family


def get_family(db: Session, family_id: UUID) -> Family:
    family = db.get(Family, family_id)
    if family is None:
        raise not_found("Family not found")
    return family


def update_family(db: Session, family: Family, member: FamilyMember, data: FamilyUpdate) -> Family:
    if member.role not in (FamilyRole.OWNER, FamilyRole.PARENT):
        raise forbidden("Parent or Owner role required")
    if data.name is not None:
        family.name = data.name.strip()
    if data.timezone is not None:
        family.timezone = data.timezone
    db.commit()
    db.refresh(family)
    return family


def list_user_families(db: Session, user_id: UUID) -> list[Family]:
    return (
        db.query(Family)
        .join(FamilyMember, FamilyMember.family_id == Family.id)
        .filter(FamilyMember.user_id == user_id)
        .order_by(Family.created_at.asc())
        .all()
    )


def list_members(db: Session, family_id: UUID) -> list[FamilyMember]:
    return (
        db.query(FamilyMember)
        .filter(FamilyMember.family_id == family_id)
        .order_by(FamilyMember.created_at.asc())
        .all()
    )


def add_member(db: Session, family_id: UUID, actor: FamilyMember, data: MemberCreate) -> FamilyMember:
    if actor.role not in (FamilyRole.OWNER, FamilyRole.PARENT):
        raise forbidden("Parent or Owner role required")
    role = data.role if data.role in VALID_ROLES else FamilyRole.CHILD
    if role == FamilyRole.OWNER:
        raise bad_request("Cannot create another Owner this way")
    member = FamilyMember(
        family_id=family_id,
        user_id=None,
        name=data.name.strip(),
        role=role,
        avatar_url=data.avatar_url,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def create_invitation(
    db: Session,
    family: Family,
    actor: FamilyMember,
    user: User,
    data: InvitationCreate,
) -> InvitationOut:
    if actor.role not in (FamilyRole.OWNER, FamilyRole.PARENT):
        raise forbidden("Parent or Owner role required")
    raw = secrets.token_urlsafe(32)
    invitation = FamilyInvitation(
        family_id=family.id,
        email=data.email.lower() if data.email else None,
        token_hash=hash_invite_token(raw),
        invited_by=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.invitation_expire_days),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    base = get_settings().public_app_url.rstrip("/")
    invite_url = f"{base}/invite/{raw}"
    if invitation.email:
        try_send_invitation_email(
            to=invitation.email,
            family_name=family.name,
            invite_url=invite_url,
            invited_by_name=user.name,
        )
    return InvitationOut(
        id=invitation.id,
        family_id=invitation.family_id,
        email=invitation.email,
        expires_at=invitation.expires_at,
        invite_token=raw,
        invite_url=invite_url,
    )


def accept_invitation(
    db: Session,
    token: str,
    user: User,
    background_tasks: BackgroundTasks | None = None,
) -> tuple[Family, FamilyMember]:
    token_hash = hash_invite_token(token)
    now = datetime.now(timezone.utc)

    invitation = (
        db.query(FamilyInvitation)
        .filter(FamilyInvitation.token_hash == token_hash)
        .first()
    )
    if invitation is None:
        raise not_found("Invitation not found")

    # Already a member: idempotent success without burning the single-use invite.
    existing = (
        db.query(FamilyMember)
        .filter(FamilyMember.family_id == invitation.family_id, FamilyMember.user_id == user.id)
        .first()
    )
    if existing:
        family = get_family(db, invitation.family_id)
        return family, existing

    # Atomic single-use claim: only one concurrent new joiner can set accepted_at.
    result = db.execute(
        update(FamilyInvitation)
        .where(
            FamilyInvitation.token_hash == token_hash,
            FamilyInvitation.accepted_at.is_(None),
            FamilyInvitation.expires_at >= now,
        )
        .values(accepted_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.expire(invitation)
        db.refresh(invitation)
        if invitation.accepted_at is not None:
            raise conflict("Invitation already used", "invite_used")
        raise bad_request("Invitation expired", "invite_expired")

    member = FamilyMember(
        family_id=invitation.family_id,
        user_id=user.id,
        name=user.name,
        role=FamilyRole.PARENT,
        avatar_url=user.avatar_url,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    family = get_family(db, invitation.family_id)
    notification_service.notify_family_members(
        db,
        family_id=family.id,
        actor_user_id=user.id,
        pref_field="family_activity",
        type="family",
        title="Family",
        body=f"{user.name} joined the family",
        entity_type="family",
        entity_id=family.id,
        background_tasks=background_tasks,
    )
    return family, member


def leave_family(db: Session, family_id: UUID, user: User) -> None:
    _advisory_lock_family(db, family_id)

    member = (
        db.query(FamilyMember)
        .filter(FamilyMember.family_id == family_id, FamilyMember.user_id == user.id)
        .first()
    )
    if member is None:
        raise not_found("Family not found")

    if member.role == FamilyRole.OWNER:
        other_owners = (
            db.query(FamilyMember)
            .filter(
                FamilyMember.family_id == family_id,
                FamilyMember.role == FamilyRole.OWNER,
                FamilyMember.id != member.id,
            )
            .count()
        )
        if other_owners == 0:
            parent = (
                db.query(FamilyMember)
                .filter(
                    FamilyMember.family_id == family_id,
                    FamilyMember.role == FamilyRole.PARENT,
                    FamilyMember.user_id.isnot(None),
                    FamilyMember.id != member.id,
                )
                .first()
            )
            if parent:
                parent.role = FamilyRole.OWNER
            else:
                raise bad_request("Owner cannot leave without another adult member", "owner_leave_blocked")

    remaining = _count_linked_adults(db, family_id, exclude_member_id=member.id)
    if remaining < 1:
        raise bad_request("Cannot leave without another adult member", "owner_leave_blocked")

    db.delete(member)
    db.commit()
    hub.disconnect_user(family_id, user.id)


def family_to_out(family: Family) -> FamilyOut:
    return FamilyOut.model_validate(family)


def member_to_out(member: FamilyMember) -> MemberOut:
    return MemberOut.model_validate(member)
