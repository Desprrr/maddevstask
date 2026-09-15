import datetime as dt

import pytest

from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.incident import Incident
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _create_check() -> Check:
    # Заводим чек напрямую в БД, а не через POST /api/checks: иначе
    # планировщик реально запустил бы фоновую пробу и добавил бы лишний
    # CheckResult, который сломал бы точные ассерты на количество точек и
    # uptime-соотношение в этих тестах на отчётность.
    async with TestSessionLocal() as db:
        check = Check(
            name="c",
            url="http://127.0.0.1:9",
            interval_seconds=30,
            timeout_ms=5000,
            expected_status_code=200,
            is_paused=True,
        )
        db.add(check)
        await db.commit()
        await db.refresh(check)
        return check


async def _record_result(
    check_id: int, success: bool, checked_at: dt.datetime, response_time_ms: int | None = 10
) -> None:
    async with TestSessionLocal() as db:
        db.add(
            CheckResult(
                check_id=check_id,
                success=success,
                checked_at=checked_at,
                response_time_ms=response_time_ms if success else None,
                status_code=200 if success else 500,
                error=None if success else "boom",
            )
        )
        await db.commit()


async def _create_incident(check_id: int, started_at: dt.datetime, ended_at: dt.datetime | None = None) -> None:
    async with TestSessionLocal() as db:
        db.add(Incident(check_id=check_id, started_at=started_at, ended_at=ended_at))
        await db.commit()


async def test_status_reflects_latest_result_and_open_incident(client) -> None:
    check = await _create_check()

    now = dt.datetime.now(dt.timezone.utc)
    await _record_result(check.id, False, now - dt.timedelta(seconds=60))
    await _record_result(check.id, False, now - dt.timedelta(seconds=30))
    await _create_incident(check.id, started_at=now - dt.timedelta(seconds=60))

    response = await client.get("/api/checks/status")
    entry = next(e for e in response.json() if e["check_id"] == check.id)

    assert entry["is_down"] is True
    assert entry["last_success"] is False
    assert entry["current_downtime_seconds"] >= 55


async def test_status_for_check_without_results_yet(client) -> None:
    check = await _create_check()

    response = await client.get("/api/checks/status")
    entry = next(e for e in response.json() if e["check_id"] == check.id)

    assert entry["last_checked_at"] is None
    assert entry["is_down"] is False


async def test_history_day_range_returns_raw_points_with_overall_uptime(client) -> None:
    check = await _create_check()
    now = dt.datetime.now(dt.timezone.utc)

    await _record_result(check.id, True, now - dt.timedelta(minutes=10), response_time_ms=100)
    await _record_result(check.id, True, now - dt.timedelta(minutes=5), response_time_ms=200)
    await _record_result(check.id, False, now - dt.timedelta(minutes=1))
    # за пределами суточного окна — не должно попасть в выборку
    await _record_result(check.id, True, now - dt.timedelta(days=2), response_time_ms=999)

    response = await client.get(f"/api/checks/{check.id}/history", params={"range": "day"})
    body = response.json()

    assert len(body["points"]) == 3
    assert body["overall_uptime_ratio"] == pytest.approx(2 / 3)


async def test_history_week_range_aggregates_by_hour(client) -> None:
    check = await _create_check()
    now = dt.datetime.now(dt.timezone.utc)
    hour_ago = now.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)

    await _record_result(check.id, True, hour_ago + dt.timedelta(minutes=5), response_time_ms=100)
    await _record_result(check.id, False, hour_ago + dt.timedelta(minutes=10))

    response = await client.get(f"/api/checks/{check.id}/history", params={"range": "week"})
    body = response.json()

    matching = [p for p in body["points"] if p["sample_count"] == 2]
    assert len(matching) == 1
    assert matching[0]["uptime_ratio"] == pytest.approx(0.5)


async def test_history_excludes_data_outside_month_window(client) -> None:
    check = await _create_check()
    now = dt.datetime.now(dt.timezone.utc)

    await _record_result(check.id, True, now - dt.timedelta(days=1), response_time_ms=50)
    await _record_result(check.id, True, now - dt.timedelta(days=40), response_time_ms=50)

    response = await client.get(f"/api/checks/{check.id}/history", params={"range": "month"})
    body = response.json()

    total_samples = sum(p["sample_count"] for p in body["points"])
    assert total_samples == 1


async def test_incidents_endpoint_orders_recent_first_with_duration(client) -> None:
    check = await _create_check()
    now = dt.datetime.now(dt.timezone.utc)

    await _create_incident(check.id, started_at=now - dt.timedelta(hours=2), ended_at=now - dt.timedelta(hours=1))
    await _create_incident(check.id, started_at=now - dt.timedelta(minutes=10))

    response = await client.get(f"/api/checks/{check.id}/incidents")
    body = response.json()

    assert len(body) == 2
    assert body[0]["ended_at"] is None  # самый недавний (открытый) — первым
    assert body[0]["duration_seconds"] is None
    assert body[1]["duration_seconds"] == 3600
