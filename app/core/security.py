from datetime import datetime, timedelta, timezone
from typing import Any, NamedTuple
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()

# bcrypt truncates/rejects beyond 72 bytes — keep hash and verify aligned.
BCRYPT_MAX_PASSWORD_BYTES = 72


class TokenClaims(NamedTuple):
    user_id: UUID
    token_version: int


def _password_bytes(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password must be at most {BCRYPT_MAX_PASSWORD_BYTES} bytes"
        )
    return encoded


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_password_bytes(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    token_version: int,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "ver": token_version,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: UUID, token_version: int = 1) -> str:
    return create_token(
        str(user_id),
        "access",
        timedelta(minutes=settings.jwt_access_token_expire_minutes),
        token_version,
    )


def create_refresh_token(user_id: UUID, token_version: int = 1) -> str:
    return create_token(
        str(user_id),
        "refresh",
        timedelta(days=settings.jwt_refresh_token_expire_days),
        token_version,
    )


def decode_token(token: str, expected_type: str) -> TokenClaims:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc
    if payload.get("type") != expected_type:
        raise ValueError("Invalid token type")
    sub = payload.get("sub")
    if not sub:
        raise ValueError("Invalid token subject")
    raw_ver = payload.get("ver", 1)
    try:
        token_version = int(raw_ver)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid token version") from exc
    return TokenClaims(user_id=UUID(sub), token_version=token_version)
