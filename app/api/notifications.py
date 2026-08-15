from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.notification import (
    NotificationOut,
    NotificationPreferencesOut,
    NotificationPreferencesUpdate,
    PushSubscribeRequest,
    PushSubscriptionOut,
    VapidPublicKeyOut,
)
from app.services import notifications as notification_service

router = APIRouter(tags=["notifications"])


@router.get("/api/notifications", response_model=list[NotificationOut])
def list_notifications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NotificationOut]:
    return [
        notification_service.notification_to_out(n)
        for n in notification_service.list_notifications(db, user.id)
    ]


@router.post("/api/notifications/{notification_id}/read", response_model=NotificationOut)
def read_notification(
    notification_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationOut:
    n = notification_service.mark_read(db, user.id, notification_id)
    return notification_service.notification_to_out(n)


@router.post("/api/notifications/read-all")
def read_all(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    count = notification_service.mark_all_read(db, user.id)
    return {"updated": count}


@router.get("/api/notification-preferences", response_model=NotificationPreferencesOut)
def get_prefs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesOut:
    return notification_service.prefs_to_out(notification_service.get_preferences(db, user.id))


@router.patch("/api/notification-preferences", response_model=NotificationPreferencesOut)
def patch_prefs(
    data: NotificationPreferencesUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationPreferencesOut:
    prefs = notification_service.update_preferences(db, user.id, data)
    return notification_service.prefs_to_out(prefs)


@router.get("/api/push/vapid-public-key", response_model=VapidPublicKeyOut)
def vapid_public_key(
    _: User = Depends(get_current_user),
) -> VapidPublicKeyOut:
    return VapidPublicKeyOut(public_key=notification_service.get_vapid_public_key())


@router.post("/api/push/subscribe", response_model=PushSubscriptionOut)
def push_subscribe(
    data: PushSubscribeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PushSubscriptionOut:
    sub = notification_service.subscribe_push(db, user, data)
    return notification_service.sub_to_out(sub)


@router.delete("/api/push/subscribe/{subscription_id}", status_code=204)
def push_unsubscribe(
    subscription_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    notification_service.unsubscribe_push(db, user.id, subscription_id)


@router.post("/api/push/test")
def push_test(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Send a test web push to the current user's subscriptions (for device setup checks)."""
    sent = notification_service.send_test_push(db, user.id)
    return {"sent": sent}
