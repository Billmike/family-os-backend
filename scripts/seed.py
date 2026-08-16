"""Seed a demo household matching the mock client (Kayode / Ade / Kita)."""

from datetime import datetime, timedelta, timezone

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.event import Event, EventMember, EventReminder
from app.models.family import Family, FamilyMember
from app.models.notification import Notification, NotificationPreference
from app.models.shopping import ShoppingItem, ShoppingList, ShoppingLocation, DEFAULT_SHOPPING_LOCATIONS
from app.models.task import Task, TaskAssignee
from app.models.user import User


def seed() -> None:
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == "kayode@familyos.app").first():
            print("Seed data already present")
            return

        kayode = User(
            email="kayode@familyos.app",
            name="Kayode",
            password_hash=hash_password("password123"),
        )
        ade = User(
            email="ade@familyos.app",
            name="Ade",
            password_hash=hash_password("password123"),
        )
        db.add_all([kayode, ade])
        db.flush()
        db.add_all(
            [
                NotificationPreference(user_id=kayode.id),
                NotificationPreference(user_id=ade.id),
            ]
        )

        family = Family(name="Ayelegun Family", timezone="Europe/Berlin")
        db.add(family)
        db.flush()

        m_kayode = FamilyMember(
            family_id=family.id, user_id=kayode.id, name="Kayode", role="Owner"
        )
        m_ade = FamilyMember(family_id=family.id, user_id=ade.id, name="Ade", role="Parent")
        m_kita = FamilyMember(family_id=family.id, user_id=None, name="Kita", role="Child")
        db.add_all([m_kayode, m_ade, m_kita])
        db.flush()

        groceries = ShoppingList(family_id=family.id, name="Groceries")
        db.add(groceries)
        for i, name in enumerate(DEFAULT_SHOPPING_LOCATIONS):
            db.add(ShoppingLocation(family_id=family.id, name=name, sort_order=i))
        db.flush()

        locations = {
            loc.name: loc
            for loc in db.query(ShoppingLocation).filter(ShoppingLocation.family_id == family.id).all()
        }

        now = datetime.now(timezone.utc)
        today = now.replace(hour=9, minute=0, second=0, microsecond=0)

        event = Event(
            family_id=family.id,
            title="School pickup",
            location="Primary School",
            starts_at=today + timedelta(hours=6),
            ends_at=today + timedelta(hours=7),
            created_by=kayode.id,
        )
        db.add(event)
        db.flush()
        db.add(EventMember(event_id=event.id, family_member_id=m_kayode.id))
        db.add(EventReminder(event_id=event.id, minutes_before=30))

        task = Task(
            family_id=family.id,
            title="Pack school bags",
            priority="high",
            category="Child",
            due_at=today + timedelta(hours=5),
            created_by=kayode.id,
        )
        db.add(task)
        db.flush()
        db.add(TaskAssignee(task_id=task.id, family_member_id=m_kayode.id))

        db.add(
            ShoppingItem(
                shopping_list_id=groceries.id,
                name="Milk",
                quantity=2,
                unit="L",
                category="Dairy",
                location_id=locations["REWE"].id,
                created_by=ade.id,
            )
        )
        db.add(
            ShoppingItem(
                shopping_list_id=groceries.id,
                name="Bananas",
                quantity=1,
                unit="bunch",
                category="Produce",
                location_id=locations["LIDL"].id,
                created_by=kayode.id,
            )
        )

        db.add(
            Notification(
                family_id=family.id,
                user_id=kayode.id,
                type="task",
                title="Task assigned",
                body="Pack school bags",
                entity_type="task",
                entity_id=task.id,
            )
        )
        db.commit()
        print("Seeded Ayelegun Family")
        print("  kayode@familyos.app / password123")
        print("  ade@familyos.app / password123")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
