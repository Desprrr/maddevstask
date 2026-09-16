import datetime as dt

from sqlalchemy import select

from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.group import Group, GroupAlertEmail
from app.models.incident import Incident
from app.models.maintenance_window import MaintenanceWindow
from app.models.sent_email import SentEmail
from tests.conftest import TestSessionLocal


async def create_group(name: str = "g", emails: tuple[str, ...] = ()) -> Group:
    async with TestSessionLocal() as db:
        group = Group(name=name)
        group.alert_emails = [GroupAlertEmail(email=e) for e in emails]
        db.add(group)
        await db.commit()
        await db.refresh(group)
        return group


async def create_check(**overrides) -> Check:
    values = dict(
        name="site",
        url="http://unused.invalid",
        interval_seconds=30,
        timeout_ms=5000,
        expected_status_code=200,
        is_paused=True,  # фоновый планировщик тесты не интересует — управляем пробами вручную
    )
    values.update(overrides)
    async with TestSessionLocal() as db:
        check = Check(**values)
        db.add(check)
        await db.commit()
        await db.refresh(check)
        return check


async def load_check(check_id: int) -> Check:
    async with TestSessionLocal() as db:
        return await db.get(Check, check_id)


async def record_result(check_id: int, success: bool, checked_at: dt.datetime) -> CheckResult:
    async with TestSessionLocal() as db:
        result = CheckResult(
            check_id=check_id,
            success=success,
            checked_at=checked_at,
            response_time_ms=5 if success else None,
            status_code=200 if success else 500,
            error=None if success else "connect to internal-db.local:5432 refused",
        )
        db.add(result)
        await db.commit()
        await db.refresh(result)
        return result


async def create_incident(check_id: int, started_at: dt.datetime, **fields) -> Incident:
    async with TestSessionLocal() as db:
        incident = Incident(check_id=check_id, started_at=started_at, **fields)
        db.add(incident)
        await db.commit()
        await db.refresh(incident)
        return incident


async def add_window(start: dt.datetime, end: dt.datetime, *, check_id=None, group_id=None) -> None:
    async with TestSessionLocal() as db:
        db.add(MaintenanceWindow(check_id=check_id, group_id=group_id, starts_at=start, ends_at=end))
        await db.commit()


async def incidents_for(check_id: int) -> list[Incident]:
    async with TestSessionLocal() as db:
        rows = await db.execute(
            select(Incident).where(Incident.check_id == check_id).order_by(Incident.started_at)
        )
        return list(rows.scalars().all())


async def sent_emails() -> list[SentEmail]:
    async with TestSessionLocal() as db:
        rows = await db.execute(select(SentEmail).order_by(SentEmail.id))
        return list(rows.scalars().all())


async def sent_subjects() -> list[str]:
    return [e.subject for e in await sent_emails()]
