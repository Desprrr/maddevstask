import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.group import Group
from app.models.incident import Incident
from app.queries import checks_with_latest_result
from app.schemas.public import PublicCheckStatus, PublicGroupStatus, PublicStatusOut

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/status", response_model=PublicStatusOut)
async def public_status(db: AsyncSession = Depends(get_db)) -> PublicStatusOut:
    """Снапшот для публичной страницы статуса — без входа. Показывает
    только чеки с is_public=true и только то, что нужно внешнему
    наблюдателю (имя, статус, аптайм), без URL/таймаутов/ожидаемых кодов —
    владелец не обязан раскрывать операционные детали."""

    rows = (await db.execute(checks_with_latest_result(Check.is_public.is_(True)))).all()
    if not rows:
        return PublicStatusOut(groups=[])
    checks = [check for check, _ in rows]
    latest_by_check = {check.id: latest for check, latest in rows if latest is not None}
    check_ids = [c.id for c in checks]

    open_incidents = {
        i.check_id: i
        for i in (
            await db.execute(
                select(Incident).where(Incident.check_id.in_(check_ids), Incident.ended_at.is_(None))
            )
        ).scalars().all()
    }

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    uptime_stmt = (
        select(
            CheckResult.check_id,
            func.sum(cast(CheckResult.success, Integer)).label("successes"),
            func.count().label("total"),
        )
        .where(CheckResult.check_id.in_(check_ids), CheckResult.checked_at >= since)
        .group_by(CheckResult.check_id)
    )
    uptime_by_check = {
        row.check_id: (row.successes / row.total if row.total else None)
        for row in (await db.execute(uptime_stmt)).all()
    }

    group_ids = {c.group_id for c in checks if c.group_id is not None}
    groups_by_id: dict[int, Group] = {}
    if group_ids:
        groups_by_id = {
            g.id: g for g in (await db.execute(select(Group).where(Group.id.in_(group_ids)))).scalars().all()
        }

    by_group: dict[int | None, list[Check]] = defaultdict(list)
    for check in checks:
        by_group[check.group_id].append(check)

    now = dt.datetime.now(dt.timezone.utc)
    result_groups: list[PublicGroupStatus] = []
    for group_id, group_checks in by_group.items():
        check_statuses = []
        for check in group_checks:
            incident = None if check.is_paused else open_incidents.get(check.id)
            latest = latest_by_check.get(check.id)
            check_statuses.append(
                PublicCheckStatus(
                    check_id=check.id,
                    name=check.name,
                    status="paused" if check.is_paused else ("down" if incident else "up"),
                    last_checked_at=latest.checked_at if latest else None,
                    current_downtime_seconds=(
                        int((now - incident.started_at).total_seconds()) if incident else None
                    ),
                    uptime_ratio_24h=uptime_by_check.get(check.id),
                )
            )
        check_statuses.sort(key=lambda cs: cs.name)
        group_status = "down" if any(cs.status == "down" for cs in check_statuses) else "up"
        result_groups.append(
            PublicGroupStatus(
                group_id=group_id,
                name=groups_by_id[group_id].name if group_id is not None else None,
                status=group_status,
                checks=check_statuses,
            )
        )

    result_groups.sort(key=lambda g: (g.group_id is None, g.name or ""))
    return PublicStatusOut(groups=result_groups)
