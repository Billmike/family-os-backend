from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid, func

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import TimestampMixin, utcnow


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recurrence_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    members = relationship("EventMember", back_populates="event", cascade="all, delete-orphan")
    reminders = relationship("EventReminder", back_populates="event", cascade="all, delete-orphan")


class EventMember(Base):
    __tablename__ = "event_members"

    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    family_member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("family_members.id", ondelete="CASCADE"), primary_key=True
    )

    event = relationship("Event", back_populates="members")


class EventReminder(Base):
    __tablename__ = "event_reminders"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    minutes_before: Mapped[int] = mapped_column(Integer, nullable=False)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event = relationship("Event", back_populates="reminders")
