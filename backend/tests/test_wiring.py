import datetime as dt

import pytest

from app.main import make_on_result
from app.models.check import Check
from app.models.check_result import CheckResult
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


class RecordingConnectionManager:
    def __init__(self) -> None:
        self.results: list[tuple[Check, CheckResult]] = []
        self.incident_events: list[tuple] = []

    async def broadcast_check_result(self, check, result) -> None:
        self.results.append((check, result))

    async def broadcast_incident_event(self, check, event) -> None:
        self.incident_events.append((check, event))


async def _create_check() -> Check:
    async with TestSessionLocal() as db:
        check = Check(
            name="c",
            url="http://unused.invalid",
            interval_seconds=30,
            timeout_ms=5000,
            expected_status_code=200,
        )
        db.add(check)
        await db.commit()
        await db.refresh(check)
        return check


async def _result_for(check: Check, success: bool, checked_at: dt.datetime) -> CheckResult:
    # Инцидент-эвалуатор читает историю результатов из БД, поэтому строка
    # должна быть реально сохранена, а не только сконструирована в памяти.
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


async def test_on_result_always_broadcasts_check_result() -> None:
    manager = RecordingConnectionManager()
    on_result = make_on_result(manager, TestSessionLocal)
    check = await _create_check()

    result = await _result_for(check, True, dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
    await on_result(check, result)

    assert len(manager.results) == 1
    assert manager.incident_events == []  # единичный успех после чистого старта — ничего не меняется


async def test_on_result_broadcasts_incident_opened_and_closed() -> None:
    manager = RecordingConnectionManager()
    on_result = make_on_result(manager, TestSessionLocal)
    check = await _create_check()

    base = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    await on_result(check, await _result_for(check, False, base))
    assert manager.incident_events == []  # один сбой — ещё не падение

    await on_result(check, await _result_for(check, False, base + dt.timedelta(seconds=30)))
    assert len(manager.incident_events) == 1
    assert manager.incident_events[0][1].kind == "opened"

    await on_result(check, await _result_for(check, True, base + dt.timedelta(seconds=60)))
    assert len(manager.incident_events) == 2
    assert manager.incident_events[1][1].kind == "closed"

    # на каждую пробу (успех/неуспех) всегда есть широковещание результата,
    # независимо от того, случился ли переход по инциденту
    assert len(manager.results) == 3
