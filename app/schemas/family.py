from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import ORMModel


class FamilyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class FamilyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)


class FamilyOut(ORMModel):
    id: UUID
    name: str
    timezone: str
    created_at: datetime
    updated_at: datetime


class MemberCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="Child")
    avatar_url: str | None = None


class MemberOut(ORMModel):
    id: UUID
    family_id: UUID
    user_id: UUID | None
    name: str
    role: str
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime


class InvitationCreate(BaseModel):
    email: EmailStr | None = None
    role: str = Field(default="Parent")


class InvitationOut(BaseModel):
    id: UUID
    family_id: UUID
    email: str | None
    expires_at: datetime
    invite_token: str
    invite_url: str


class InvitationAcceptOut(BaseModel):
    family: FamilyOut
    member: MemberOut
