import datetime as dt
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_connection_manager, get_scheduler
from app.db import get_db
from app.incidents import close_incident_for_pause
from app.queries import checks_with_latest_result
from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.group import Group
from app.models.incident import Incident
from app.realtime.connection_manager import ConnectionManager
from app.schemas.check import (
    CheckCreate,
    CheckHistoryOut,
    CheckOut,
    CheckResultOut,
    CheckStatusOut,
    CheckUpdate,
    HistoryPoint,
)
from app.schemas.incident import IncidentOut
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


async def _announce_change(connection_manager: ConnectionManager, *, affects_public: bool) -> None:
    await connection_manager.broadcast_admin_changed()
    if affects_public:
        await connection_manager.broadcast_public_changed()


@router.post("", response_model=CheckOut, status_code=201)
async def create_check(
    payload: CheckCreate,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> Check:
    await _ensure_group_exists(db, payload.group_id)
    check = Check(**payload.model_dump())
    db.add(check)
    await db.commit()
    await db.refresh(check)
    if not check.is_paused:
        scheduler.add(check)
    await _announce_change(connection_manager, affects_public=check.is_public)
    return check


@router.get("", response_model=list[CheckOut])
async def list_checks(group_id: int | None = None, db: AsyncSession = Depends(get_db)) -> list[Check]:
    stmt = select(Check).order_by(Check.id)
    if group_id is not None:
        stmt = stmt.where(Check.group_id == group_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ВАЖНО: этот литеральный путь должен быть зарегистрирован раньше
# "/{check_id}" ниже, иначе Starlette сначала попытается сматчить "/status"
# как check_id (и упадёт в 422 вместо вызова этого хендлера) — порядок
# роутов имеет значение при совпадении формы пути.
@router.get("/status", response_model=list[CheckStatusOut])
async def list_checks_status(db: AsyncSession = Depends(get_db)) -> list[CheckStatusOut]:
    rows = (await db.execute(checks_with_latest_result())).all()
    checks = [check for check, _ in rows]
    latest_by_check = {check.id: latest for check, latest in rows if latest is not None}
    check_ids = [c.id for c in checks]
    if not check_ids:
        return []

    open_incidents_stmt = select(Incident).where(
        Incident.check_id.in_(check_ids), Incident.ended_at.is_(None)
    )
    open_by_check = {i.check_id: i for i in (await db.execute(open_incidents_stmt)).scalars().all()}

    now = dt.datetime.now(dt.timezone.utc)
    out: list[CheckStatusOut] = []
    for check in checks:
        latest = latest_by_check.get(check.id)
        incident = open_by_check.get(check.id)
        out.append(
            CheckStatusOut(
                check_id=check.id,
                name=check.name,
                group_id=check.group_id,
                is_paused=check.is_paused,
                last_checked_at=latest.checked_at if latest else None,
                last_success=latest.success if latest else None,
                last_response_time_ms=latest.response_time_ms if latest else None,
                is_down=incident is not None,
                current_incident_started_at=incident.started_at if incident else None,
                current_downtime_seconds=(
                    int((now - incident.started_at).total_seconds()) if incident else None
                ),
            )
        )
    return out


@router.get("/{check_id}", response_model=CheckOut)
async def get_check(check_id: int, db: AsyncSession = Depends(get_db)) -> Check:
    return await _get_or_404(db, check_id)


@router.get("/{check_id}/history", response_model=CheckHistoryOut)
async def check_history(
    check_id: int,
    range: Literal["day", "week", "month"] = "day",
    db: AsyncSession = Depends(get_db),
) -> CheckHistoryOut:
    await _get_or_404(db, check_id)
    now = dt.datetime.now(dt.timezone.utc)

    if range == "day":
        since = now - dt.timedelta(days=1)
        rows = (
            await db.execute(
                select(CheckResult)
                .where(CheckResult.check_id == check_id, CheckResult.checked_at >= since)
                .order_by(CheckResult.checked_at)
            )
        ).scalars().all()
        points = [
            HistoryPoint(
                bucket_start=r.checked_at,
                avg_response_time_ms=float(r.response_time_ms) if r.response_time_ms is not None else None,
                uptime_ratio=1.0 if r.success else 0.0,
                sample_count=1,
            )
            for r in rows
        ]
        total = len(rows)
        successes = sum(1 for r in rows if r.success)
    else:
        since = now - (dt.timedelta(weeks=1) if range == "week" else dt.timedelta(days=30))
        bucket = "hour" if range == "week" else "day"
        bucket_col = func.date_trunc(bucket, CheckResult.checked_at).label("bucket_start")
        stmt = (
            select(
                bucket_col,
                func.avg(CheckResult.response_time_ms).label("avg_response_time_ms"),
                func.sum(cast(CheckResult.success, Integer)).label("successes"),
                func.count().label("total"),
            )
            .where(CheckResult.check_id == check_id, CheckResult.checked_at >= since)
            .group_by(bucket_col)
            .order_by(bucket_col)
        )
        rows = (await db.execute(stmt)).all()
        points = [
            HistoryPoint(
                bucket_start=r.bucket_start,
                avg_response_time_ms=float(r.avg_response_time_ms) if r.avg_response_time_ms is not None else None,
                uptime_ratio=(r.successes / r.total) if r.total else None,
                sample_count=r.total,
            )
            for r in rows
        ]
        total = sum(r.total for r in rows)
        successes = sum(r.successes for r in rows)

    overall_uptime_ratio = (successes / total) if total else None
    return CheckHistoryOut(range=range, points=points, overall_uptime_ratio=overall_uptime_ratio)


@router.get("/{check_id}/incidents", response_model=list[IncidentOut])
async def check_incidents(check_id: int, db: AsyncSession = Depends(get_db)) -> list[IncidentOut]:
    await _get_or_404(db, check_id)
    rows = (
        await db.execute(
            select(Incident)
            .where(Incident.check_id == check_id)
            .order_by(Incident.started_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return [
        IncidentOut(
            id=i.id,
            check_id=i.check_id,
            started_at=i.started_at,
            ended_at=i.ended_at,
            duration_seconds=(
                int((i.ended_at - i.started_at).total_seconds()) if i.ended_at is not None else None
            ),
            end_reason=i.end_reason,
        )
        for i in rows
    ]


@router.patch("/{check_id}", response_model=CheckOut)
async def update_check(
    check_id: int,
    payload: CheckUpdate,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> Check:
    check = await _get_or_404(db, check_id)
    was_public = check.is_public
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
    await _announce_change(connection_manager, affects_public=was_public or check.is_public)
    return check


@router.delete("/{check_id}", status_code=204)
async def delete_check(
    check_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> None:
    check = await _get_or_404(db, check_id)
    was_public = check.is_public
    await scheduler.remove(check_id)
    await db.delete(check)
    await db.commit()
    await _announce_change(connection_manager, affects_public=was_public)


@router.post("/{check_id}/pause", response_model=CheckOut)
async def pause_check(
    check_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> Check:
    await scheduler.remove(check_id)  # сначала остановить пробы, чтобы не прилетел результат после закрытия
    check = await _get_or_404(db, check_id)
    check.is_paused = True
    closed = await close_incident_for_pause(db, check)
    await db.commit()
    await db.refresh(check)
    if closed is not None:
        await connection_manager.broadcast_incident_event(check, closed)
    await _announce_change(connection_manager, affects_public=check.is_public)
    return check


@router.post("/{check_id}/resume", response_model=CheckOut)
async def resume_check(
    check_id: int,
    db: AsyncSession = Depends(get_db),
    scheduler: Scheduler = Depends(get_scheduler),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> Check:
    check = await _get_or_404(db, check_id)
    check.is_paused = False
    await db.commit()
    await db.refresh(check)
    await scheduler.resume(check_id)
    await _announce_change(connection_manager, affects_public=check.is_public)
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
