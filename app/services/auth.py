from sqlalchemy.orm import Session

from app.core.deps import user_from_token
from app.core.exceptions import bad_request, conflict, unauthorized
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.notification import NotificationPreference
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services import password_reset as password_reset_service
from app.services.assistant import is_assistant_available


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
    password_reset_service.consume_outstanding_resets(db, user.id)
    db.commit()
    return user, _tokens_for(user)


def refresh_tokens(db: Session, refresh_token: str) -> TokenResponse:
    user = user_from_token(db, refresh_token, "refresh")
    return _tokens_for(user)


def request_password_reset(db: Session, *, email: str, client_ip: str) -> None:
    password_reset_service.request_password_reset(db, email=email, client_ip=client_ip)


def reset_password(db: Session, *, token: str, password: str) -> tuple[User, TokenResponse]:
    row = password_reset_service.get_valid_reset_token(db, token)
    if row is None:
        raise bad_request(
            password_reset_service.INVALID_RESET_DETAIL,
            password_reset_service.INVALID_RESET_CODE,
        )
    user = db.get(User, row.user_id)
    if user is None:
        raise bad_request(
            password_reset_service.INVALID_RESET_DETAIL,
            password_reset_service.INVALID_RESET_CODE,
        )
    user.password_hash = hash_password(password)
    user.token_version += 1
    password_reset_service.consume_outstanding_resets(db, user.id)
    db.commit()
    db.refresh(user)
    return user, _tokens_for(user)


def user_to_out(user: User) -> UserOut:
    return UserOut.model_validate(user).model_copy(
        update={"assistant_enabled": is_assistant_available()}
    )


def _tokens_for(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.token_version),
        refresh_token=create_refresh_token(user.id, user.token_version),
    )
