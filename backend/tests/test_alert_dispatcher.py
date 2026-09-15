import datetime as dt

import pytest
from sqlalchemy import select

from app.alerting.dispatcher import AlertDispatcher
from app.alerting.email_sender import FakeEmailSender
from app.models.check import Check
from app.models.group import Group, GroupAlertEmail
from app.models.incident import Incident
from app.models.maintenance_window import MaintenanceWindow
from app.models.sent_email import SentEmail
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio

NOW = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)


async def _create_group_with_emails(*emails: str) -> Group:
    async with TestSessionLocal() as db:
        group = Group(name="g")
        group.alert_emails = [GroupAlertEmail(email=e) for e in emails]
        db.add(group)
        await db.commit()
        await db.refresh(group)
        return group


async def _create_check(group_id: int | None = None) -> Check:
    async with TestSessionLocal() as db:
        check = Check(
            name="site",
            url="http://unused.invalid",
            group_id=group_id,
            interval_seconds=30,
            timeout_ms=5000,
            expected_status_code=200,
        )
        db.add(check)
        await db.commit()
        await db.refresh(check)
        return check


async def _create_incident(check_id: int, started_at: dt.datetime, ended_at: dt.datetime | None = None) -> Incident:
    async with TestSessionLocal() as db:
        incident = Incident(check_id=check_id, started_at=started_at, ended_at=ended_at)
        db.add(incident)
        await db.commit()
        await db.refresh(incident)
        return incident


async def _sent_emails() -> list[SentEmail]:
    async with TestSessionLocal() as db:
        return list((await db.execute(select(SentEmail))).scalars().all())


def _dispatcher() -> AlertDispatcher:
    return AlertDispatcher(TestSessionLocal, FakeEmailSender(TestSessionLocal))


async def test_down_email_sent_for_open_incident() -> None:
    group = await _create_group_with_emails("ops@example.com")
    check = await _create_check(group_id=group.id)
    await _create_incident(check.id, started_at=NOW)

    await _dispatcher().run_once()

    emails = await _sent_emails()
    assert len(emails) == 1
    assert emails[0].to_email == "ops@example.com"
    assert "DOWN" in emails[0].subject


async def test_recovered_email_sent_when_closed() -> None:
    group = await _create_group_with_emails("ops@example.com")
    check = await _create_check(group_id=group.id)
    ended = NOW + dt.timedelta(minutes=5)
    incident = await _create_incident(check.id, started_at=NOW, ended_at=ended)

    await _dispatcher().run_once()

    emails = await _sent_emails()
    subjects = sorted(e.subject for e in emails)
    assert any("DOWN" in s for s in subjects)
    assert any("RECOVERED" in s for s in subjects)
    assert len(emails) == 2  # down + recovered, каждое ровно один раз


async def test_repeated_sweep_does_not_resend() -> None:
    group = await _create_group_with_emails("ops@example.com")
    check = await _create_check(group_id=group.id)
    await _create_incident(check.id, started_at=NOW)

    dispatcher = _dispatcher()
    await dispatcher.run_once()
    await dispatcher.run_once()
    await dispatcher.run_once()

    emails = await _sent_emails()
    assert len(emails) == 1


async def test_check_without_group_has_no_recipients_but_is_marked_processed() -> None:
    check = await _create_check(group_id=None)
    await _create_incident(check.id, started_at=NOW)

    dispatcher = _dispatcher()
    await dispatcher.run_once()
    assert await _sent_emails() == []

    # помечено обработанным - второй прогон не пытается заново и не падает
    await dispatcher.run_once()
    assert await _sent_emails() == []

    async with TestSessionLocal() as db:
        incident = (await db.execute(select(Incident))).scalar_one()
        assert incident.alert_down_sent_at is not None


async def test_maintenance_window_suppresses_email_until_it_ends() -> None:
    group = await _create_group_with_emails("ops@example.com")
    check = await _create_check(group_id=group.id)
    await _create_incident(check.id, started_at=NOW)

    window_ends_at = NOW + dt.timedelta(minutes=10)
    async with TestSessionLocal() as db:
        db.add(
            MaintenanceWindow(
                check_id=check.id,
                starts_at=NOW - dt.timedelta(minutes=5),
                ends_at=window_ends_at,
            )
        )
        await db.commit()

    dispatcher = _dispatcher()

    # "Сейчас" - середина окна: письма не должно быть.
    await dispatcher.run_once(now=NOW + dt.timedelta(minutes=1))
    assert await _sent_emails() == []

    # Окно закончилось, падение всё ещё не отмечено восстановленным —
    # письмо должно уйти на первом же проходе после конца окна.
    await dispatcher.run_once(now=window_ends_at + dt.timedelta(seconds=1))
    emails = await _sent_emails()
    assert len(emails) == 1
    assert "DOWN" in emails[0].subject
