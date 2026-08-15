from enum import StrEnum
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import forbidden, not_found, unauthorized
from app.core.security import decode_token
from app.models.family import FamilyMember
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


class FamilyRole(StrEnum):
    OWNER = "Owner"
    PARENT = "Parent"
    CHILD = "Child"


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    try:
        user_id = decode_token(credentials.credentials, "access")
    except ValueError as exc:
        raise unauthorized(str(exc)) from exc
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized("User not found")
    return user


def get_membership(db: Session, family_id: UUID, user_id: UUID) -> FamilyMember:
    member = (
        db.query(FamilyMember)
        .filter(FamilyMember.family_id == family_id, FamilyMember.user_id == user_id)
        .first()
    )
    if member is None:
        raise not_found("Family not found")
    return member


def require_family_member(
    family_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FamilyMember:
    return get_membership(db, family_id, user.id)


def require_parent_or_owner(member: FamilyMember) -> FamilyMember:
    if member.role not in (FamilyRole.OWNER, FamilyRole.PARENT):
        raise forbidden("Parent or Owner role required")
    return member
