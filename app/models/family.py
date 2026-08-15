from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import TimestampMixin, utcnow


class Family(Base, TimestampMixin):
    __tablename__ = "families"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="UTC")

    members = relationship("FamilyMember", back_populates="family", cascade="all, delete-orphan")
    invitations = relationship("FamilyInvitation", back_populates="family", cascade="all, delete-orphan")
    shopping_lists = relationship("ShoppingList", back_populates="family", cascade="all, delete-orphan")


class FamilyMember(Base, TimestampMixin):
    __tablename__ = "family_members"
    __table_args__ = (
        Index(
            "uq_family_members_family_user",
            "family_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
            sqlite_where=text("user_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    family = relationship("Family", back_populates="members")
    user = relationship("User", back_populates="members")


class FamilyInvitation(Base):
    __tablename__ = "family_invitations"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    invited_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=utcnow
    )

    family = relationship("Family", back_populates="invitations")
