from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_connection_manager
from app.db import get_db
from app.models.check import Check
from app.models.group import Group, GroupAlertEmail
from app.realtime.connection_manager import ConnectionManager
from app.schemas.group import GroupCreate, GroupOut, GroupUpdate

router = APIRouter(prefix="/groups", tags=["groups"])


def _to_out(group: Group) -> GroupOut:
    return GroupOut(
        id=group.id,
        name=group.name,
        created_at=group.created_at,
        alert_emails=[e.email for e in group.alert_emails],
    )


async def _get_or_404(db: AsyncSession, group_id: int) -> Group:
    result = await db.execute(
        select(Group).where(Group.id == group_id).options(selectinload(Group.alert_emails))
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@router.post("", response_model=GroupOut, status_code=201)
async def create_group(
    payload: GroupCreate,
    db: AsyncSession = Depends(get_db),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> GroupOut:
    group = Group(name=payload.name)
    group.alert_emails = [GroupAlertEmail(email=str(e)) for e in payload.alert_emails]
    db.add(group)
    await db.commit()
    await db.refresh(group, attribute_names=["alert_emails"])
    await connection_manager.broadcast_admin_changed()
    return _to_out(group)


@router.get("", response_model=list[GroupOut])
async def list_groups(db: AsyncSession = Depends(get_db)) -> list[GroupOut]:
    result = await db.execute(select(Group).options(selectinload(Group.alert_emails)).order_by(Group.id))
    return [_to_out(g) for g in result.scalars().all()]


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(group_id: int, db: AsyncSession = Depends(get_db)) -> GroupOut:
    group = await _get_or_404(db, group_id)
    return _to_out(group)


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: int,
    payload: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> GroupOut:
    group = await _get_or_404(db, group_id)
    renamed = payload.name is not None and payload.name != group.name

    if payload.name is not None:
        group.name = payload.name
    if payload.alert_emails is not None:
        group.alert_emails = [GroupAlertEmail(email=str(e)) for e in payload.alert_emails]

    await db.commit()
    await db.refresh(group, attribute_names=["alert_emails"])
    await connection_manager.broadcast_admin_changed()
    # Адреса оповещений на публичной странице не видны, а имя группы — видно.
    if renamed and await _has_public_checks(db, group_id):
        await connection_manager.broadcast_public_changed()
    return _to_out(group)


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    connection_manager: ConnectionManager = Depends(get_connection_manager),
) -> None:
    group = await _get_or_404(db, group_id)
    had_public_checks = await _has_public_checks(db, group_id)  # после удаления их group_id станет NULL
    await db.delete(group)
    await db.commit()
    await connection_manager.broadcast_admin_changed()
    if had_public_checks:
        await connection_manager.broadcast_public_changed()


async def _has_public_checks(db: AsyncSession, group_id: int) -> bool:
    row = await db.execute(
        select(Check.id).where(Check.group_id == group_id, Check.is_public.is_(True)).limit(1)
    )
    return row.first() is not None
