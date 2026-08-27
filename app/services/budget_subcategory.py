from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, not_found
from app.models.budget_group import (
    BUDGET_GROUPS,
    GROUP_DIRECTIONS,
    LEGACY_CATEGORY_SEED,
    ROLE_GROCERIES,
)
from app.models.budget_subcategory import BudgetSubcategory
from app.models.family import Family
from app.models.user import utcnow
from app.realtime.hub import hub
from app.schemas.budget_subcategory import (
    BudgetSubcategoryCreate,
    BudgetSubcategoryGroupOut,
    BudgetSubcategoryListOut,
    BudgetSubcategoryOut,
    BudgetSubcategoryUpdate,
)


def subcategory_to_out(row: BudgetSubcategory) -> BudgetSubcategoryOut:
    return BudgetSubcategoryOut(
        id=row.id,
        family_id=row.family_id,
        group=row.group,
        name=row.name,
        sort_order=row.sort_order,
        role=row.role,
        archived_at=row.archived_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_subcategory(db: Session, subcategory_id: UUID) -> BudgetSubcategory:
    row = db.get(BudgetSubcategory, subcategory_id)
    if row is None or row.archived_at is not None:
        raise not_found("Budget subcategory not found")
    return row


def get_subcategory_any(db: Session, subcategory_id: UUID) -> BudgetSubcategory:
    """Return subcategory even if archived (for historical ledger display)."""
    row = db.get(BudgetSubcategory, subcategory_id)
    if row is None:
        raise not_found("Budget subcategory not found")
    return row


def seed_default_subcategories(db: Session, family_id: UUID) -> list[BudgetSubcategory]:
    existing = (
        db.query(BudgetSubcategory)
        .filter(BudgetSubcategory.family_id == family_id)
        .count()
    )
    if existing > 0:
        return (
            db.query(BudgetSubcategory)
            .filter(
                BudgetSubcategory.family_id == family_id,
                BudgetSubcategory.archived_at.is_(None),
            )
            .order_by(BudgetSubcategory.sort_order, BudgetSubcategory.name)
            .all()
        )

    rows: list[BudgetSubcategory] = []
    for sort_order, (_legacy, (group, name, role)) in enumerate(LEGACY_CATEGORY_SEED.items()):
        row = BudgetSubcategory(
            family_id=family_id,
            group=group,
            name=name,
            sort_order=sort_order,
            role=role,
        )
        db.add(row)
        rows.append(row)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def ensure_family_subcategories(db: Session, family_id: UUID) -> list[BudgetSubcategory]:
    rows = (
        db.query(BudgetSubcategory)
        .filter(
            BudgetSubcategory.family_id == family_id,
            BudgetSubcategory.archived_at.is_(None),
        )
        .order_by(BudgetSubcategory.sort_order, BudgetSubcategory.name)
        .all()
    )
    if rows:
        return rows
    return seed_default_subcategories(db, family_id)


def list_subcategories(db: Session, family: Family) -> BudgetSubcategoryListOut:
    rows = ensure_family_subcategories(db, family.id)
    by_group: dict[str, list[BudgetSubcategoryOut]] = {g: [] for g in BUDGET_GROUPS}
    for row in rows:
        if row.group in by_group:
            by_group[row.group].append(subcategory_to_out(row))
        else:
            by_group.setdefault(row.group, []).append(subcategory_to_out(row))

    groups = [
        BudgetSubcategoryGroupOut(
            group=group,
            direction=GROUP_DIRECTIONS[group],
            subcategories=by_group.get(group, []),
        )
        for group in BUDGET_GROUPS
    ]
    return BudgetSubcategoryListOut(groups=groups)


def _assert_unique_name(
    db: Session,
    family_id: UUID,
    group: str,
    name: str,
    *,
    exclude_id: UUID | None = None,
) -> None:
    query = db.query(BudgetSubcategory).filter(
        BudgetSubcategory.family_id == family_id,
        BudgetSubcategory.group == group,
        func.lower(BudgetSubcategory.name) == name.lower(),
        BudgetSubcategory.archived_at.is_(None),
    )
    if exclude_id is not None:
        query = query.filter(BudgetSubcategory.id != exclude_id)
    if query.first() is not None:
        raise bad_request(f"Subcategory '{name}' already exists in {group}")


def create_subcategory(
    db: Session,
    family: Family,
    data: BudgetSubcategoryCreate,
) -> BudgetSubcategoryOut:
    ensure_family_subcategories(db, family.id)
    _assert_unique_name(db, family.id, data.group, data.name)
    sort_order = data.sort_order
    if sort_order is None:
        max_order = (
            db.query(func.max(BudgetSubcategory.sort_order))
            .filter(
                BudgetSubcategory.family_id == family.id,
                BudgetSubcategory.group == data.group,
                BudgetSubcategory.archived_at.is_(None),
            )
            .scalar()
        )
        sort_order = (max_order or 0) + 1

    row = BudgetSubcategory(
        family_id=family.id,
        group=data.group,
        name=data.name,
        sort_order=sort_order,
        role=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    out = subcategory_to_out(row)
    hub.broadcast(
        family.id,
        {"type": "budget_subcategory.updated", "subcategory": out.model_dump(mode="json")},
    )
    return out


def update_subcategory(
    db: Session,
    family: Family,
    row: BudgetSubcategory,
    data: BudgetSubcategoryUpdate,
) -> BudgetSubcategoryOut:
    if row.family_id != family.id:
        raise not_found("Budget subcategory not found")
    fields = data.model_fields_set
    new_group = data.group if "group" in fields and data.group is not None else row.group
    new_name = data.name if "name" in fields and data.name is not None else row.name
    if new_group != row.group or new_name.lower() != row.name.lower():
        _assert_unique_name(db, family.id, new_group, new_name, exclude_id=row.id)
    if "group" in fields and data.group is not None:
        row.group = data.group
    if "name" in fields and data.name is not None:
        row.name = data.name
    if "sort_order" in fields and data.sort_order is not None:
        row.sort_order = data.sort_order
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    out = subcategory_to_out(row)
    hub.broadcast(
        family.id,
        {"type": "budget_subcategory.updated", "subcategory": out.model_dump(mode="json")},
    )
    return out


def archive_subcategory(db: Session, family: Family, row: BudgetSubcategory) -> None:
    if row.family_id != family.id:
        raise not_found("Budget subcategory not found")
    if row.role == ROLE_GROCERIES:
        raise bad_request("The Groceries subcategory cannot be archived")
    row.archived_at = datetime.now(timezone.utc)
    row.updated_at = utcnow()
    db.commit()
    hub.broadcast(
        family.id,
        {"type": "budget_subcategory.deleted", "subcategory_id": str(row.id)},
    )


def groceries_subcategory(db: Session, family_id: UUID) -> BudgetSubcategory:
    ensure_family_subcategories(db, family_id)
    row = (
        db.query(BudgetSubcategory)
        .filter(
            BudgetSubcategory.family_id == family_id,
            BudgetSubcategory.role == ROLE_GROCERIES,
            BudgetSubcategory.archived_at.is_(None),
        )
        .first()
    )
    if row is None:
        raise bad_request("Groceries subcategory is not configured for this family")
    return row


def subcategory_for_legacy_category(
    db: Session,
    family_id: UUID,
    legacy_category: str,
) -> BudgetSubcategory:
    """Map a legacy AI/extraction category string onto a seeded subcategory."""
    ensure_family_subcategories(db, family_id)
    seed = LEGACY_CATEGORY_SEED.get(legacy_category)
    if seed is None:
        seed = LEGACY_CATEGORY_SEED["Other"]
    group, name, role = seed
    query = db.query(BudgetSubcategory).filter(
        BudgetSubcategory.family_id == family_id,
        BudgetSubcategory.archived_at.is_(None),
    )
    if role is not None:
        row = query.filter(BudgetSubcategory.role == role).first()
        if row is not None:
            return row
    row = query.filter(
        BudgetSubcategory.group == group,
        func.lower(BudgetSubcategory.name) == name.lower(),
    ).first()
    if row is not None:
        return row
    return groceries_subcategory(db, family_id) if role == ROLE_GROCERIES else (
        db.query(BudgetSubcategory)
        .filter(
            BudgetSubcategory.family_id == family_id,
            BudgetSubcategory.archived_at.is_(None),
        )
        .order_by(BudgetSubcategory.sort_order)
        .first()
        or groceries_subcategory(db, family_id)
    )
