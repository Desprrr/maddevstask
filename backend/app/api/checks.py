from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_scheduler
from app.db import get_db
from app.models.check import Check
from app.models.group import Group
from app.schemas.check import CheckCreate, CheckOut, CheckResultOut, CheckUpdate
from app.scheduler.engine import Scheduler

router = APIRouter(prefix="/checks", tags=["checks"])


async def _get_or_404(db: AsyncSession, check_id: int) -> Check:
    check = await db.get(Check, check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Check not found")
    return check


async def _ensure_group_exists(db: AsyncSession, group_id: int | None) -> None:
    if group_id is None:
        return
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")


@router.post("", response_model=CheckOut, status_code=201)
async def create_check(
    payload: CheckCreate,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
) -> Check:
    await _ensure_group_exists(db, payload.group_id)
    check = Check(**payload.model_dump())
    db.add(check)
    await db.commit()
    await db.refresh(check)
    if not check.is_paused:
        scheduler.add(check)
    return check


@router.get("", response_model=list[CheckOut])
async def list_checks(group_id: int | None = None, db: AsyncSession = Depends(get_db)) -> list[Check]:
    stmt = select(Check).order_by(Check.id)
    if group_id is not None:
        stmt = stmt.where(Check.group_id == group_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{check_id}", response_model=CheckOut)
async def get_check(check_id: int, db: AsyncSession = Depends(get_db)) -> Check:
    return await _get_or_404(db, check_id)


@router.patch("/{check_id}", response_model=CheckOut)
async def update_check(
    check_id: int,
    payload: CheckUpdate,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
) -> Check:
    check = await _get_or_404(db, check_id)
    updates = payload.model_dump(exclude_unset=True)

    if "group_id" in updates:
        await _ensure_group_exists(db, updates["group_id"])

    for field, value in updates.items():
        setattr(check, field, value)

    await db.commit()
    await db.refresh(check)
    # Перезапускаем задачу планировщика, чтобы новые interval/url/timeout
    # подхватились сразу, а не только со следующего случайного цикла.
    await scheduler.restart(check_id)
    return check


@router.delete("/{check_id}", status_code=204)
async def delete_check(
    check_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
) -> None:
    check = await _get_or_404(db, check_id)
    await scheduler.remove(check_id)
    await db.delete(check)
    await db.commit()


@router.post("/{check_id}/pause", response_model=CheckOut)
async def pause_check(
    check_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
) -> Check:
    check = await _get_or_404(db, check_id)
    check.is_paused = True
    await db.commit()
    await db.refresh(check)
    await scheduler.remove(check_id)
    return check


@router.post("/{check_id}/resume", response_model=CheckOut)
async def resume_check(
    check_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
) -> Check:
    check = await _get_or_404(db, check_id)
    check.is_paused = False
    await db.commit()
    await db.refresh(check)
    await scheduler.resume(check_id)
    return check


@router.post("/{check_id}/run-now", response_model=CheckResultOut)
async def run_check_now(
    check_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
) -> CheckResultOut:
    await _get_or_404(db, check_id)
    result = await scheduler.trigger_now(check_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Check not found")
    return CheckResultOut.model_validate(result)
