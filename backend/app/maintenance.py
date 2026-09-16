from __future__ import annotations

import datetime as dt

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.check import Check
from app.models.maintenance_window import MaintenanceWindow


async def maintenance_overlaps(db: AsyncSession, check: Check, start: dt.datetime, end: dt.datetime) -> bool:
    """Пересекается ли [start, end] с каким-либо окном обслуживания этого чека
    (напрямую или через его группу)."""
    conditions = [MaintenanceWindow.check_id == check.id]
    if check.group_id is not None:
        conditions.append(MaintenanceWindow.group_id == check.group_id)

    stmt = select(MaintenanceWindow.id).where(
        or_(*conditions),
        MaintenanceWindow.starts_at <= end,
        MaintenanceWindow.ends_at >= start,
    )
    return (await db.execute(stmt)).first() is not None


async def is_in_maintenance(db: AsyncSession, check: Check, now: dt.datetime) -> bool:
    """Активно ли для этого чека окно обслуживания на момент `now`."""
    return await maintenance_overlaps(db, check, now, now)
