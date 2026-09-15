import datetime as dt

import pytest
from sqlalchemy import select

from app.incidents import make_incident_evaluator
from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.incident import Incident
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio

BASE = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


async def _create_check(**overrides) -> Check:
    defaults = dict(
        name="t",
        url="http://unused.invalid",
        interval_seconds=30,
        timeout_ms=5000,
        expected_status_code=200,
    )
    defaults.update(overrides)
    async with TestSessionLocal() as db:
        check = Check(**defaults)
        db.add(check)
        await db.commit()
        await db.refresh(check)
        return check


async def _record_result(check: Check, success: bool, checked_at: dt.datetime) -> CheckResult:
    async with TestSessionLocal() as db:
        result = CheckResult(
            check_id=check.id,
            success=success,
            checked_at=checked_at,
            response_time_ms=5 if success else None,
            status_code=200 if success else 500,
            error=None if success else "boom",
        )
        db.add(result)
        await db.commit()
        await db.refresh(result)
        return result


async def _incidents(check_id: int) -> list[Incident]:
    async with TestSessionLocal() as db:
        rows = (await db.execute(select(Incident).where(Incident.check_id == check_id))).scalars().all()
        return list(rows)


async def test_single_failure_does_not_open_incident() -> None:
    check = await _create_check()
    evaluate = make_incident_evaluator(TestSessionLocal)

    result = await _record_result(check, False, BASE)
    await evaluate(check, result)

    assert await _incidents(check.id) == []


async def test_two_consecutive_failures_open_incident_at_first_failure() -> None:
    check = await _create_check()
    evaluate = make_incident_evaluator(TestSessionLocal)

    r1 = await _record_result(check, False, BASE)
    await evaluate(check, r1)
    r2 = await _record_result(check, False, BASE + dt.timedelta(seconds=30))
    await evaluate(check, r2)

    incidents = await _incidents(check.id)
    assert len(incidents) == 1
    assert incidents[0].started_at == BASE
    assert incidents[0].ended_at is None


async def test_success_in_between_resets_the_streak() -> None:
    check = await _create_check()
    evaluate = make_incident_evaluator(TestSessionLocal)

    sequence = [False, True, False]
    for i, ok in enumerate(sequence):
        r = await _record_result(check, ok, BASE + dt.timedelta(seconds=30 * i))
        await evaluate(check, r)

    # только один сбой подряд к этому моменту (True разорвал серию) — падением не считается
    assert await _incidents(check.id) == []


async def test_incident_closes_on_first_success() -> None:
    check = await _create_check()
    evaluate = make_incident_evaluator(TestSessionLocal)

    for i in range(2):
        r = await _record_result(check, False, BASE + dt.timedelta(seconds=30 * i))
        await evaluate(check, r)

    r3 = await _record_result(check, True, BASE + dt.timedelta(seconds=60))
    await evaluate(check, r3)

    incidents = await _incidents(check.id)
    assert len(incidents) == 1
    assert incidents[0].ended_at == BASE + dt.timedelta(seconds=60)


async def test_further_failures_do_not_duplicate_incident() -> None:
    check = await _create_check()
    evaluate = make_incident_evaluator(TestSessionLocal)

    for i in range(5):
        r = await _record_result(check, False, BASE + dt.timedelta(seconds=30 * i))
        await evaluate(check, r)

    assert len(await _incidents(check.id)) == 1


async def test_restart_safety_open_incident_is_reused_not_duplicated() -> None:
    check = await _create_check()
    evaluate = make_incident_evaluator(TestSessionLocal)

    # Инцидент, "открытый до перезапуска сервера" — evaluate ничего о нём не
    # знает из памяти, только из БД.
    async with TestSessionLocal() as db:
        db.add(Incident(check_id=check.id, started_at=BASE))
        await db.commit()

    r = await _record_result(check, False, BASE + dt.timedelta(seconds=300))
    await evaluate(check, r)

    incidents = await _incidents(check.id)
    assert len(incidents) == 1
    assert incidents[0].ended_at is None

    r2 = await _record_result(check, True, BASE + dt.timedelta(seconds=330))
    await evaluate(check, r2)

    incidents = await _incidents(check.id)
    assert len(incidents) == 1
    assert incidents[0].ended_at == BASE + dt.timedelta(seconds=330)
