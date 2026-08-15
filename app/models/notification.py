from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid, func

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import utcnow


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=utcnow
    )


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    calendar_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    task_assignments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    task_due_soon: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    shopping_activity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    family_activity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    quiet_hours_start: Mapped[str | None] = mapped_column(String, nullable=True)
    quiet_hours_end: Mapped[str | None] = mapped_column(String, nullable=True)

    user = relationship("User", back_populates="notification_preferences")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=utcnow
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
