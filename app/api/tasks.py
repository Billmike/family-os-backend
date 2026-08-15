from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, get_membership, require_family_member
from app.models.family import FamilyMember
from app.models.user import User
from app.schemas.task import TaskCreate, TaskOut, TaskUpdate
from app.services import tasks as task_service

router = APIRouter(tags=["tasks"])


@router.get("/api/families/{family_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    family_id: UUID,
    filter: str = Query(default="all", pattern="^(all|mine|completed|open)$"),
    member: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    tasks = task_service.list_tasks(db, family_id, filter_mode=filter, member_id=member.id)
    return [task_service.task_to_out(t) for t in tasks]


@router.post("/api/families/{family_id}/tasks", response_model=TaskOut)
def create_task(
    family_id: UUID,
    data: TaskCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    _: FamilyMember = Depends(require_family_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = task_service.create_task(db, family_id, user, data, background_tasks=background_tasks)
    return task_service.task_to_out(task)


@router.patch("/api/tasks/{task_id}", response_model=TaskOut)
def patch_task(
    task_id: UUID,
    data: TaskUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = task_service.get_family_task(db, task_id)
    get_membership(db, task.family_id, user.id)
    task = task_service.update_task(db, task, data, actor=user, background_tasks=background_tasks)
    return task_service.task_to_out(task)


@router.post("/api/tasks/{task_id}/complete", response_model=TaskOut)
def complete_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = task_service.get_family_task(db, task_id)
    get_membership(db, task.family_id, user.id)
    task = task_service.complete_task(db, task, user)
    return task_service.task_to_out(task)


@router.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    task = task_service.get_family_task(db, task_id)
    get_membership(db, task.family_id, user.id)
    task_service.delete_task(db, task)
