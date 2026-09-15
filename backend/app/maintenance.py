from __future__ import annotations

import datetime as dt

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.check import Check
from app.models.maintenance_window import MaintenanceWindow


async def is_in_maintenance(db: AsyncSession, check: Check, now: dt.datetime) -> bool:
    """Активно ли для этого чека (напрямую или через его группу) окно
    обслуживания на момент `now`."""
    conditions = [MaintenanceWindow.check_id == check.id]
    if check.group_id is not None:
        conditions.append(MaintenanceWindow.group_id == check.group_id)

    stmt = select(MaintenanceWindow.id).where(
        or_(*conditions),
        MaintenanceWindow.starts_at <= now,
        MaintenanceWindow.ends_at >= now,
    )
    result = await db.execute(stmt)
    return result.first() is not None
