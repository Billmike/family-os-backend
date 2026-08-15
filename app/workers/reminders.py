import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.timeutil import ensure_aware
from app.models.event import Event, EventReminder
from app.models.family import Family, FamilyMember
from app.models.task import Task
from app.schemas.event import MAX_REMINDER_MINUTES
from app.services import notifications as notification_service

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def process_reminders() -> None:
    db: Session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(minutes=2)
        # Only load reminders that could fire soon (minutes_before capped at MAX_REMINDER_MINUTES).
        reminders = (
            db.query(EventReminder)
            .join(Event)
            .filter(
                Event.starts_at >= now - timedelta(minutes=5),
                Event.starts_at <= now + timedelta(minutes=MAX_REMINDER_MINUTES + 2),
            )
            .all()
        )
        for reminder in reminders:
            event = reminder.event
            fire_at = ensure_aware(event.starts_at) - timedelta(minutes=reminder.minutes_before)
            if fire_at > window_end or fire_at < now - timedelta(minutes=5):
                continue
            if reminder.last_fired_at is not None:
                last = ensure_aware(reminder.last_fired_at)
                if last >= fire_at - timedelta(minutes=1):
                    continue
            family = db.get(Family, event.family_id)
            if family is None:
                continue
            members = (
                db.query(FamilyMember)
                .filter(FamilyMember.family_id == event.family_id, FamilyMember.user_id.isnot(None))
                .all()
            )
            for member in members:
                assert member.user_id is not None
                prefs = notification_service.ensure_preferences(db, member.user_id)
                if not prefs.calendar_reminders:
                    continue
                notification_service.create_notification(
                    db,
                    family_id=event.family_id,
                    user_id=member.user_id,
                    type="calendar",
                    title="Upcoming event",
                    body=event.title,
                    entity_type="event",
                    entity_id=event.id,
                )
            reminder.last_fired_at = now
            db.commit()

        # Task due soon (within next hour, incomplete)
        due_soon = (
            db.query(Task)
            .filter(
                Task.completed_at.is_(None),
                Task.due_at.isnot(None),
                Task.due_at <= now + timedelta(hours=1),
                Task.due_at >= now - timedelta(minutes=5),
                Task.last_due_soon_notified_at.is_(None),
            )
            .all()
        )
        for task in due_soon:
            for assignee in task.assignees:
                member = db.get(FamilyMember, assignee.family_member_id)
                if member is None or member.user_id is None:
                    continue
                prefs = notification_service.ensure_preferences(db, member.user_id)
                if not prefs.task_due_soon:
                    continue
                notification_service.create_notification(
                    db,
                    family_id=task.family_id,
                    user_id=member.user_id,
                    type="task",
                    title="Task due soon",
                    body=task.title,
                    entity_type="task",
                    entity_id=task.id,
                    push=True,
                )
            # One delivery attempt per due window (matches EventReminder.last_fired_at).
            task.last_due_soon_notified_at = now
            db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Reminder job failed")
        db.rollback()
    finally:
        db.close()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(process_reminders, "interval", minutes=1, id="reminders", replace_existing=True)
    scheduler.start()
    logger.info("Reminder scheduler started")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
