from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_connection_manager
from app.db import get_db
from app.models.check import Check
from app.models.group import Group
from app.models.maintenance_window import MaintenanceWindow
from app.realtime.connection_manager import ConnectionManager
from app.schemas.maintenance_window import MaintenanceWindowCreate, MaintenanceWindowOut

router = APIRouter(prefix="/maintenance-windows", tags=["maintenance-windows"])


@router.post("", response_model=MaintenanceWindowOut, status_code=201)
async def create_maintenance_window(
    payload: MaintenanceWindowCreate,
    db: AsyncSession = Depends(get_db),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> MaintenanceWindow:
    if payload.check_id is not None and await db.get(Check, payload.check_id) is None:
        raise HTTPException(status_code=404, detail="Check not found")
    if payload.group_id is not None and await db.get(Group, payload.group_id) is None:
        raise HTTPException(status_code=404, detail="Group not found")

    window = MaintenanceWindow(**payload.model_dump())
    db.add(window)
    await db.commit()
    await db.refresh(window)
    await connection_manager.broadcast_admin_changed()
    return window


@router.get("", response_model=list[MaintenanceWindowOut])
async def list_maintenance_windows(
    check_id: int | None = None,
    group_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> list[MaintenanceWindow]:
    stmt = select(MaintenanceWindow).order_by(MaintenanceWindow.starts_at)
    if check_id is not None:
        stmt = stmt.where(MaintenanceWindow.check_id == check_id)
    if group_id is not None:
        stmt = stmt.where(MaintenanceWindow.group_id == group_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.delete("/{window_id}", status_code=204)
async def delete_maintenance_window(
    window_id: int,
    db: AsyncSession = Depends(get_db),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> None:
    window = await db.get(MaintenanceWindow, window_id)
    if window is None:
        raise HTTPException(status_code=404, detail="Maintenance window not found")
    await db.delete(window)
    await db.commit()
    await connection_manager.broadcast_admin_changed()
