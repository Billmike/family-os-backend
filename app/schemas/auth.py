from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# bcrypt accepts at most 72 bytes; reject longer passwords so hashing cannot 500.
MAX_PASSWORD_BYTES = 72
MAX_PASSWORD_CHARS = 128


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _validate_password_bytes(password: str) -> str:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must be at most {MAX_PASSWORD_BYTES} bytes")
    return password


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_CHARS)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("password")
    @classmethod
    def password_byte_limit(cls, value: str) -> str:
        return _validate_password_bytes(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_CHARS)

    @field_validator("password")
    @classmethod
    def password_byte_limit(cls, value: str) -> str:
        return _validate_password_bytes(value)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(ORMModel):
    id: UUID
    email: EmailStr
    name: str
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime
