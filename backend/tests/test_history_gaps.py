"""История проверки явно показывает, когда мониторинг не работал.

Пока сервер (или сама проверка) стоял, результатов нет. На графике с категориальной осью
соседние точки просто склеивались, и простой монитора был не виден. Теперь эндпоинт истории
отдаёт границы периода и интервалы без данных (`gaps`), а график строится по оси времени."""

import datetime as dt

import pytest

from app.models.check_result import CheckResult
from tests.conftest import TestSessionLocal
from tests.factories import create_check

pytestmark = pytest.mark.asyncio

# interval 30с + timeout 5с → порог разрыва 2×30 + 5 = 65с


def _ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value)


async def _series(check_id: int, start: dt.datetime, end: dt.datetime, step_seconds: int = 30) -> None:
    """Результаты раз в step_seconds на [start, end]."""
    async with TestSessionLocal() as db:
        at = start
        while at <= end:
            db.add(CheckResult(check_id=check_id, checked_at=at, success=True, response_time_ms=20))
            at += dt.timedelta(seconds=step_seconds)
        await db.commit()


async def _history(client, check_id: int, range_: str) -> dict:
    response = await client.get(f"/api/checks/{check_id}/history", params={"range": range_})
    assert response.status_code == 200
    return response.json()


def _gap_list(body: dict) -> list[tuple[dt.datetime, dt.datetime]]:
    return [(_ts(g["start"]), _ts(g["end"])) for g in body["gaps"]]


def _close(a: dt.datetime, b: dt.datetime, seconds: float = 2) -> bool:
    return abs((a - b).total_seconds()) <= seconds


async def test_day_range_reports_monitor_downtime_between_results(client) -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    check = await create_check(created_at=now - dt.timedelta(hours=3))
    await _series(check.id, now - dt.timedelta(hours=3), now - dt.timedelta(hours=2))
    await _series(check.id, now - dt.timedelta(minutes=40), now - dt.timedelta(seconds=10))

    body = await _history(client, check.id, "day")

    assert _gap_list(body) == [(now - dt.timedelta(hours=2), now - dt.timedelta(minutes=40))]
    assert _close(_ts(body["range_end"]), dt.datetime.now(dt.timezone.utc))
    assert _close(_ts(body["range_start"]), dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1))
    # простой монитора — не простой сайта: в процент доступности не входит
    assert body["overall_uptime_ratio"] == 1.0


async def test_late_probe_within_threshold_is_not_a_gap(client) -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    check = await create_check(created_at=now - dt.timedelta(minutes=10))
    await _series(check.id, now - dt.timedelta(minutes=10), now - dt.timedelta(minutes=5))
    # следующая проба пришла через 60с (медленный сайт + таймаут) — это не разрыв
    await _series(check.id, now - dt.timedelta(minutes=4), now - dt.timedelta(seconds=5), step_seconds=60)

    body = await _history(client, check.id, "day")

    assert body["gaps"] == []


async def test_week_range_reports_gap_between_hour_buckets(client) -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    check = await create_check(created_at=now - dt.timedelta(hours=6))
    await _series(check.id, now - dt.timedelta(hours=6), now - dt.timedelta(hours=5), step_seconds=60)
    await _series(check.id, now - dt.timedelta(hours=2), now - dt.timedelta(seconds=20), step_seconds=60)

    body = await _history(client, check.id, "week")

    assert _gap_list(body) == [(now - dt.timedelta(hours=5), now - dt.timedelta(hours=2))]
    buckets = [_ts(p["bucket_start"]) for p in body["points"]]
    assert all(b <= now - dt.timedelta(hours=5) or b >= now - dt.timedelta(hours=3) for b in buckets)


async def test_monitoring_stopped_until_now_is_a_trailing_gap(client) -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    check = await create_check(created_at=now - dt.timedelta(hours=1))
    await _series(check.id, now - dt.timedelta(hours=1), now - dt.timedelta(minutes=30))

    body = await _history(client, check.id, "day")

    [(start, end)] = _gap_list(body)
    assert start == now - dt.timedelta(minutes=30)
    assert _close(end, dt.datetime.now(dt.timezone.utc))


async def test_period_before_first_result_is_a_gap_but_not_before_creation(client) -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    created = await create_check(created_at=now - dt.timedelta(hours=2))
    await _series(created.id, now - dt.timedelta(minutes=30), now - dt.timedelta(seconds=10))
    old = await create_check(created_at=now - dt.timedelta(days=10))
    await _series(old.id, now - dt.timedelta(hours=20), now - dt.timedelta(seconds=10), step_seconds=60)

    # проверка создана 2ч назад, а первый результат — полчаса назад: сервер не работал
    [(start, end)] = _gap_list(await _history(client, created.id, "day"))
    assert (start, end) == (now - dt.timedelta(hours=2), now - dt.timedelta(minutes=30))

    # проверка старше периода: данных нет с начала суток до первого результата
    [(start, end)] = _gap_list(await _history(client, old.id, "day"))
    assert _close(start, dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1))
    assert end == now - dt.timedelta(hours=20)


async def test_check_without_any_results_is_one_gap(client) -> None:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    check = await create_check(created_at=now - dt.timedelta(hours=1))

    body = await _history(client, check.id, "day")

    [(start, end)] = _gap_list(body)
    assert start == now - dt.timedelta(hours=1)
    assert _close(end, dt.datetime.now(dt.timezone.utc))
    assert body["points"] == []
