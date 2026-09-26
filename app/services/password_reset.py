import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.rate_limit import reset_ip_limiter
from app.models.password_reset import PasswordResetToken
from app.models.user import User
from app.services.email import try_send_password_reset_email

RESET_IP_MAX = 10
RESET_WINDOW_SECONDS = 15 * 60
RESET_COOLDOWN = timedelta(minutes=15)
INVALID_RESET_DETAIL = "This link is invalid or expired."
INVALID_RESET_CODE = "invalid_reset_link"


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def consume_outstanding_resets(db: Session, user_id: UUID) -> None:
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.consumed_at.is_(None),
    ).update({"consumed_at": datetime.now(timezone.utc)})


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _has_recent_reset_email(db: Session, user_id: UUID) -> bool:
    cutoff = datetime.now(timezone.utc) - RESET_COOLDOWN
    recent = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user_id)
        .order_by(PasswordResetToken.created_at.desc())
        .first()
    )
    if recent is None:
        return False
    return _as_utc(recent.created_at) >= cutoff


def request_password_reset(db: Session, *, email: str, client_ip: str) -> None:
    ip_allowed = reset_ip_limiter.allow(
        client_ip,
        max_hits=RESET_IP_MAX,
        window_seconds=RESET_WINDOW_SECONDS,
    )
    user = db.query(User).filter(User.email == email.lower()).first()
    if not ip_allowed or user is None:
        return
    if _has_recent_reset_email(db, user.id):
        return

    settings = get_settings()
    raw = secrets.token_urlsafe(32)
    consume_outstanding_resets(db, user.id)
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_reset_token(raw),
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.password_reset_expire_minutes),
    )
    db.add(row)
    db.commit()

    base = settings.public_app_url.rstrip("/")
    reset_url = f"{base}/reset/{raw}"
    sent = try_send_password_reset_email(to=user.email, reset_url=reset_url)
    if sent:
        return
    db.delete(row)
    db.commit()


def get_valid_reset_token(db: Session, raw_token: str) -> PasswordResetToken | None:
    token_hash = hash_reset_token(raw_token)
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash)
        .first()
    )
    if row is None or row.consumed_at is not None:
        return None
    if _as_utc(row.expires_at) <= datetime.now(timezone.utc):
        return None
    return row
