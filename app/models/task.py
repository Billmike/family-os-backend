from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.user import TimestampMixin


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    family_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    priority: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    recurrence_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_due_soon_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    assignees = relationship("TaskAssignee", back_populates="task", cascade="all, delete-orphan")


class TaskAssignee(Base):
    __tablename__ = "task_assignees"

    task_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    family_member_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("family_members.id", ondelete="CASCADE"), primary_key=True
    )

    task = relationship("Task", back_populates="assignees")
