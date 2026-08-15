from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.timeutil import day_bounds, family_now
from app.models.family import Family, FamilyMember
from app.models.shopping import ShoppingItem, ShoppingList
from app.models.task import Task
from app.schemas.notification import DashboardOut
from app.services.events import list_events
from app.services.shopping import item_to_out
from app.services.tasks import task_to_out


def get_dashboard(db: Session, family: Family, member: FamilyMember) -> DashboardOut:
    start, end = day_bounds(family.timezone)
    today_events = list_events(db, family.id, start, end)
    upcoming_end = end + timedelta(days=14)
    upcoming = [
        e
        for e in list_events(db, family.id, end, upcoming_end)
        if (e.occurrence_starts_at or e.starts_at) >= end
    ][:10]

    open_tasks = (
        db.query(Task)
        .filter(Task.family_id == family.id, Task.completed_at.is_(None))
        .order_by(Task.due_at.asc().nullslast(), Task.created_at.desc())
        .limit(10)
        .all()
    )

    groceries = (
        db.query(ShoppingList)
        .filter(ShoppingList.family_id == family.id)
        .order_by(ShoppingList.created_at.asc())
        .first()
    )
    shopping_preview: list = []
    if groceries:
        items = (
            db.query(ShoppingItem)
            .filter(
                ShoppingItem.shopping_list_id == groceries.id,
                ShoppingItem.completed_at.is_(None),
            )
            .order_by(ShoppingItem.created_at.desc())
            .limit(8)
            .all()
        )
        shopping_preview = [item_to_out(i) for i in items]

    now = family_now(family.timezone)
    return DashboardOut(
        family_id=family.id,
        family_name=family.name,
        timezone=family.timezone,
        member_name=member.name,
        date=now.date().isoformat(),
        today_events=today_events,
        open_tasks=[task_to_out(t) for t in open_tasks],
        shopping_preview=shopping_preview,
        upcoming_events=upcoming,
    )
