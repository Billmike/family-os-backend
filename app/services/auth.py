from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import conflict, unauthorized
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.notification import NotificationPreference
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut


def register_user(db: Session, data: RegisterRequest) -> tuple[User, TokenResponse]:
    existing = db.query(User).filter(User.email == data.email.lower()).first()
    if existing:
        raise conflict("Email already registered", "email_taken")
    user = User(
        email=data.email.lower(),
        name=data.name.strip(),
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.flush()
    prefs = NotificationPreference(user_id=user.id)
    db.add(prefs)
    db.commit()
    db.refresh(user)
    return user, _tokens_for(user)


def login_user(db: Session, data: LoginRequest) -> tuple[User, TokenResponse]:
    user = db.query(User).filter(User.email == data.email.lower()).first()
    if user is None or not verify_password(data.password, user.password_hash):
        raise unauthorized("Invalid email or password", "invalid_credentials")
    return user, _tokens_for(user)


def refresh_tokens(db: Session, refresh_token: str) -> TokenResponse:
    try:
        user_id = decode_token(refresh_token, "refresh")
    except ValueError as exc:
        raise unauthorized(str(exc)) from exc
    user = db.get(User, user_id)
    if user is None:
        raise unauthorized("User not found")
    return _tokens_for(user)


def user_to_out(user: User) -> UserOut:
    return UserOut.model_validate(user)


def _tokens_for(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )
