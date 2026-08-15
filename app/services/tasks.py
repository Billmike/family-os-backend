from datetime import datetime, timezone
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.core.exceptions import bad_request, not_found
from app.core.timeutil import ensure_aware, next_occurrence
from app.models.family import FamilyMember
from app.models.task import Task, TaskAssignee
from app.models.user import User
from app.realtime.hub import hub
from app.schemas.task import TaskCreate, TaskOut, TaskUpdate
from app.services import notifications as notification_service


def _broadcast_task(task: Task, type_: str) -> None:
    hub.broadcast(
        task.family_id,
        {"type": type_, "task": task_to_out(task).model_dump(mode="json")},
    )


def task_to_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        family_id=task.family_id,
        title=task.title,
        description=task.description,
        due_at=task.due_at,
        priority=task.priority,
        category=task.category,
        recurrence_rule=task.recurrence_rule,
        completed_at=task.completed_at,
        created_by=task.created_by,
        assignee_ids=[a.family_member_id for a in task.assignees],
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _validate_assignees(db: Session, family_id: UUID, assignee_ids: list[UUID]) -> None:
    if not assignee_ids:
        return
    count = (
        db.query(FamilyMember)
        .filter(FamilyMember.family_id == family_id, FamilyMember.id.in_(assignee_ids))
        .count()
    )
    if count != len(set(assignee_ids)):
        raise bad_request("One or more assignees are not in this family")


def create_task(
    db: Session,
    family_id: UUID,
    user: User,
    data: TaskCreate,
    background_tasks: BackgroundTasks | None = None,
) -> Task:
    _validate_assignees(db, family_id, data.assignee_ids)
    task = Task(
        family_id=family_id,
        title=data.title.strip(),
        description=data.description,
        due_at=ensure_aware(data.due_at) if data.due_at else None,
        priority=data.priority or "normal",
        category=data.category,
        recurrence_rule=data.recurrence_rule,
        created_by=user.id,
    )
    db.add(task)
    db.flush()
    for aid in data.assignee_ids:
        db.add(TaskAssignee(task_id=task.id, family_member_id=aid))
    db.commit()
    db.refresh(task)
    _broadcast_task(task, "task.created")
    notification_service.notify_task_assigned(
        db, task, actor_user_id=user.id, background_tasks=background_tasks
    )
    return task


def get_family_task(db: Session, task_id: UUID) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise not_found("Task not found")
    return task


def list_tasks(
    db: Session,
    family_id: UUID,
    *,
    filter_mode: str = "all",
    member_id: UUID | None = None,
) -> list[Task]:
    q = db.query(Task).filter(Task.family_id == family_id)
    if filter_mode == "completed":
        q = q.filter(Task.completed_at.isnot(None))
    elif filter_mode in ("all", "mine", "open"):
        if filter_mode != "completed":
            # "all" includes both; "mine"/"open" show incomplete by default for open
            if filter_mode == "open":
                q = q.filter(Task.completed_at.is_(None))
    if filter_mode == "mine" and member_id is not None:
        q = (
            q.join(TaskAssignee, TaskAssignee.task_id == Task.id)
            .filter(TaskAssignee.family_member_id == member_id)
            .filter(Task.completed_at.is_(None))
        )
    return q.order_by(Task.due_at.asc().nullslast(), Task.created_at.desc()).all()


def update_task(
    db: Session,
    task: Task,
    data: TaskUpdate,
    actor: User | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> Task:
    previous_assignee_ids: set[UUID] | None = None
    if data.assignee_ids is not None:
        previous_assignee_ids = {a.family_member_id for a in task.assignees}
    if data.title is not None:
        task.title = data.title.strip()
    if data.description is not None:
        task.description = data.description
    if data.due_at is not None:
        new_due = ensure_aware(data.due_at)
        if task.due_at is None or ensure_aware(task.due_at) != new_due:
            task.last_due_soon_notified_at = None
        task.due_at = new_due
    if data.priority is not None:
        task.priority = data.priority
    if data.category is not None:
        task.category = data.category
    if data.recurrence_rule is not None:
        task.recurrence_rule = data.recurrence_rule
    if data.completed_at is not None:
        task.completed_at = ensure_aware(data.completed_at)
    if data.assignee_ids is not None:
        _validate_assignees(db, task.family_id, data.assignee_ids)
        task.assignees.clear()
        db.flush()
        for aid in data.assignee_ids:
            db.add(TaskAssignee(task_id=task.id, family_member_id=aid))
    task.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(task)
    _broadcast_task(task, "task.updated")
    if previous_assignee_ids is not None and actor is not None:
        notification_service.notify_task_assigned(
            db,
            task,
            actor_user_id=actor.id,
            background_tasks=background_tasks,
            previous_assignee_ids=previous_assignee_ids,
        )
    return task


def complete_task(db: Session, task: Task, user: User) -> Task:
    if task.completed_at is not None:
        return task
    now = datetime.now(timezone.utc)
    task.completed_at = now
    task.updated_at = now
    next_task = None
    if task.recurrence_rule:
        base = ensure_aware(task.due_at) if task.due_at else now
        nxt = next_occurrence(base, task.recurrence_rule)
        if nxt is not None:
            next_task = Task(
                family_id=task.family_id,
                title=task.title,
                description=task.description,
                due_at=nxt,
                priority=task.priority,
                category=task.category,
                recurrence_rule=task.recurrence_rule,
                created_by=user.id,
            )
            db.add(next_task)
            db.flush()
            for a in task.assignees:
                db.add(TaskAssignee(task_id=next_task.id, family_member_id=a.family_member_id))
    db.commit()
    db.refresh(task)
    _broadcast_task(task, "task.updated")
    if next_task is not None:
        db.refresh(next_task)
        _broadcast_task(next_task, "task.created")
    return task


def delete_task(db: Session, task: Task) -> None:
    family_id = task.family_id
    task_id = task.id
    db.delete(task)
    db.commit()
    hub.broadcast(family_id, {"type": "task.deleted", "task_id": str(task_id)})
