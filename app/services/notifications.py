import ipaddress
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError, bad_request, not_found
from app.models.family import FamilyMember
from app.models.notification import Notification, NotificationPreference, PushSubscription
from app.models.task import Task
from app.models.user import User, utcnow
from app.realtime.hub import hub
from app.schemas.notification import (
    NotificationOut,
    NotificationPreferencesOut,
    NotificationPreferencesUpdate,
    PushSubscribeRequest,
    PushSubscriptionOut,
)

logger = logging.getLogger(__name__)
settings = get_settings()

PUSH_TIMEOUT_SECONDS = 5

# Known Web Push service hostnames / suffixes (SSRF allowlist).
_ALLOWED_PUSH_HOSTS = frozenset(
    {
        "fcm.googleapis.com",
        "android.googleapis.com",
        "updates.push.services.mozilla.com",
        "web.push.apple.com",
    }
)
_ALLOWED_PUSH_HOST_SUFFIXES = (
    ".googleapis.com",
    ".notify.windows.com",
    ".push.apple.com",
    ".push.services.mozilla.com",
)


def validate_push_endpoint(url: str) -> None:
    """Reject non-HTTPS, IP literals, and hosts outside known push providers."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise bad_request("Push endpoint must use HTTPS", "invalid_push_endpoint")
    if parsed.username is not None or parsed.password is not None:
        raise bad_request("Invalid push endpoint", "invalid_push_endpoint")
    host = parsed.hostname
    if not host:
        raise bad_request("Invalid push endpoint", "invalid_push_endpoint")
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise bad_request("Push endpoint must not be an IP address", "invalid_push_endpoint")
    if host in _ALLOWED_PUSH_HOSTS:
        return
    if any(host.endswith(suffix) for suffix in _ALLOWED_PUSH_HOST_SUFFIXES):
        return
    raise bad_request("Push endpoint host is not allowed", "invalid_push_endpoint")


def ensure_preferences(db: Session, user_id: UUID) -> NotificationPreference:
    prefs = db.get(NotificationPreference, user_id)
    if prefs is None:
        prefs = NotificationPreference(user_id=user_id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


def _send_push_in_background(user_id: UUID, payload: dict) -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        send_push_to_user(db, user_id, payload)
    finally:
        db.close()


_PUSH_URL_BY_TYPE = {
    "calendar": "/?go=calendar",
    "task": "/?go=tasks",
    "shopping": "/?go=shopping",
    "family": "/?go=notifications",
}


def _vapid_sub_claim() -> str:
    """Web Push requires sub to be a mailto: or https: URI."""
    contact = (settings.vapid_contact_email or "").strip()
    if contact.startswith("mailto:") or contact.startswith("https:"):
        return contact
    if contact:
        return f"mailto:{contact}"
    return "mailto:admin@familyos.app"


def create_notification(
    db: Session,
    *,
    family_id: UUID,
    user_id: UUID,
    type: str,
    title: str,
    body: str,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    push: bool = True,
    background_tasks: BackgroundTasks | None = None,
) -> Notification:
    notif = Notification(
        family_id=family_id,
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    hub.send_to_user(
        family_id,
        user_id,
        {
            "type": "notification.created",
            "notification": notification_to_out(notif).model_dump(mode="json"),
        },
    )
    if push:
        payload: dict = {
            "title": title,
            "body": body,
            "type": type,
            "notification_id": str(notif.id),
            "url": _PUSH_URL_BY_TYPE.get(type, "/"),
        }
        if entity_type:
            payload["entity_type"] = entity_type
        if entity_id is not None:
            payload["entity_id"] = str(entity_id)
        if background_tasks is not None:
            background_tasks.add_task(_send_push_in_background, user_id, payload)
        else:
            send_push_to_user(db, user_id, payload)
    return notif


def notify_family_members(
    db: Session,
    *,
    family_id: UUID,
    actor_user_id: UUID,
    pref_field: str,
    type: str,
    title: str,
    body: str,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> None:
    members = (
        db.query(FamilyMember)
        .filter(
            FamilyMember.family_id == family_id,
            FamilyMember.user_id.isnot(None),
            FamilyMember.user_id != actor_user_id,
        )
        .all()
    )
    for member in members:
        assert member.user_id is not None
        prefs = ensure_preferences(db, member.user_id)
        if not getattr(prefs, pref_field):
            continue
        create_notification(
            db,
            family_id=family_id,
            user_id=member.user_id,
            type=type,
            title=title,
            body=body,
            entity_type=entity_type,
            entity_id=entity_id,
            background_tasks=background_tasks,
        )


def notify_task_assigned(
    db: Session,
    task: Task,
    actor_user_id: UUID,
    background_tasks: BackgroundTasks | None = None,
    previous_assignee_ids: set[UUID] | None = None,
) -> None:
    previous = previous_assignee_ids or set()
    for assignee in task.assignees:
        if assignee.family_member_id in previous:
            continue
        member = db.get(FamilyMember, assignee.family_member_id)
        if member is None or member.user_id is None or member.user_id == actor_user_id:
            continue
        prefs = ensure_preferences(db, member.user_id)
        if not prefs.task_assignments:
            continue
        create_notification(
            db,
            family_id=task.family_id,
            user_id=member.user_id,
            type="task",
            title="Task assigned",
            body=f"You were assigned: {task.title}",
            entity_type="task",
            entity_id=task.id,
            background_tasks=background_tasks,
        )


def list_notifications(db: Session, user_id: UUID, limit: int = 50) -> list[Notification]:
    return (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )


def mark_read(db: Session, user_id: UUID, notification_id: UUID) -> Notification:
    notif = db.get(Notification, notification_id)
    if notif is None or notif.user_id != user_id:
        raise not_found("Notification not found")
    if notif.read_at is None:
        notif.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notif)
    return notif


def mark_all_read(db: Session, user_id: UUID) -> int:
    now = datetime.now(timezone.utc)
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .update({"read_at": now})
    )
    db.commit()
    return updated


def get_preferences(db: Session, user_id: UUID) -> NotificationPreference:
    return ensure_preferences(db, user_id)


def update_preferences(
    db: Session, user_id: UUID, data: NotificationPreferencesUpdate
) -> NotificationPreference:
    prefs = ensure_preferences(db, user_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(prefs, field, value)
    db.commit()
    db.refresh(prefs)
    return prefs


def subscribe_push(db: Session, user: User, data: PushSubscribeRequest) -> PushSubscription:
    validate_push_endpoint(data.endpoint)
    existing = (
        db.query(PushSubscription)
        .filter(PushSubscription.user_id == user.id, PushSubscription.endpoint == data.endpoint)
        .first()
    )
    if existing:
        existing.p256dh = data.p256dh
        existing.auth = data.auth
        existing.user_agent = data.user_agent
        existing.last_used_at = utcnow()
        db.commit()
        db.refresh(existing)
        return existing
    sub = PushSubscription(
        user_id=user.id,
        endpoint=data.endpoint,
        p256dh=data.p256dh,
        auth=data.auth,
        user_agent=data.user_agent,
        last_used_at=utcnow(),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def unsubscribe_push(db: Session, user_id: UUID, subscription_id: UUID) -> None:
    sub = db.get(PushSubscription, subscription_id)
    if sub is None or sub.user_id != user_id:
        raise not_found("Subscription not found")
    db.delete(sub)
    db.commit()


def get_vapid_public_key() -> str | None:
    key = settings.vapid_public_key.strip()
    return key or None


def send_push_to_user(db: Session, user_id: UUID, payload: dict) -> None:
    if not settings.vapid_private_key or not settings.vapid_public_key:
        logger.warning("VAPID keys not configured; skipping push")
        return
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush not available")
        return

    subs = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
    if not subs:
        logger.debug("No push subscriptions for user %s", user_id)
        return
    vapid_claims = {"sub": _vapid_sub_claim()}
    for sub in subs:
        try:
            validate_push_endpoint(sub.endpoint)
        except AppError:
            logger.info("Removing invalid push subscription %s", sub.id)
            db.delete(sub)
            db.commit()
            continue
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=json.dumps(payload),
                vapid_private_key=settings.vapid_private_key,
                vapid_claims=vapid_claims,
                timeout=PUSH_TIMEOUT_SECONDS,
            )
            sub.last_used_at = utcnow()
            db.commit()
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                logger.info("Removing expired push subscription %s (HTTP %s)", sub.id, status)
                db.delete(sub)
                db.commit()
            else:
                logger.info("Push failed for %s: %s", sub.id, exc)
        except Exception as exc:  # noqa: BLE001
            logger.info("Push failed for %s: %s", sub.id, exc)


def notification_to_out(n: Notification) -> NotificationOut:
    return NotificationOut.model_validate(n)


def prefs_to_out(p: NotificationPreference) -> NotificationPreferencesOut:
    return NotificationPreferencesOut.model_validate(p)


def sub_to_out(s: PushSubscription) -> PushSubscriptionOut:
    return PushSubscriptionOut.model_validate(s)
