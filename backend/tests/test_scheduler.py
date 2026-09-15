import asyncio

import pytest

from app.models.check import Check
from app.scheduler.engine import Scheduler
from app.scheduler.prober import ProbeOutcome
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


class ProbeSpy:
    """Подменяет реальную HTTP-пробу управляемой асинхронной заглушкой и
    следит за максимальной наблюдаемой параллельностью вызовов на один check."""

    def __init__(self, delay: float = 0.05) -> None:
        self.calls = 0
        self.concurrent = 0
        self.max_concurrent = 0
        self.delay = delay

    async def __call__(self, check: Check) -> ProbeOutcome:
        self.calls += 1
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.concurrent -= 1
        return ProbeOutcome(success=True, response_time_ms=1, status_code=200, error=None)


async def _create_check(**overrides) -> Check:
    defaults = dict(
        name="test",
        url="http://unused.invalid",
        interval_seconds=30,
        timeout_ms=5000,
        expected_status_code=200,
        is_paused=False,
        is_public=False,
    )
    defaults.update(overrides)
    async with TestSessionLocal() as db:
        check = Check(**defaults)
        db.add(check)
        await db.commit()
        await db.refresh(check)
        return check


async def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.01) -> None:
    elapsed = 0.0
    while not predicate():
        if elapsed >= timeout:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(interval)
        elapsed += interval


async def test_add_runs_first_probe_promptly(monkeypatch) -> None:
    spy = ProbeSpy(delay=0.01)
    monkeypatch.setattr("app.scheduler.engine.probe", spy)
    check = await _create_check()

    scheduler = Scheduler(TestSessionLocal)
    try:
        scheduler.add(check)
        await _wait_until(lambda: spy.calls >= 1)
        assert spy.calls == 1
        assert spy.max_concurrent == 1
    finally:
        await scheduler.shutdown()


async def test_trigger_now_after_cycle_starts_a_fresh_run(monkeypatch) -> None:
    spy = ProbeSpy(delay=0.05)
    monkeypatch.setattr("app.scheduler.engine.probe", spy)
    check = await _create_check()

    scheduler = Scheduler(TestSessionLocal)
    try:
        scheduler.add(check)
        await _wait_until(lambda: scheduler._states[check.id].last_result is not None)  # noqa: SLF001

        first_result_id = scheduler._states[check.id].last_result.id  # noqa: SLF001 (внутренний тест)
        result = await scheduler.trigger_now(check.id)

        assert result is not None
        assert result.id != first_result_id
        assert spy.calls == 2
        assert spy.max_concurrent == 1  # ни разу не было двух проб одновременно
    finally:
        await scheduler.shutdown()


async def test_trigger_now_never_overlaps_even_if_probe_still_inflight(monkeypatch) -> None:
    spy = ProbeSpy(delay=0.2)
    monkeypatch.setattr("app.scheduler.engine.probe", spy)
    check = await _create_check()

    scheduler = Scheduler(TestSessionLocal)
    try:
        scheduler.add(check)
        await asyncio.sleep(0.02)  # run-now попадает точно в момент, когда первая проба ещё выполняется
        result = await scheduler.trigger_now(check.id)
        assert result is not None

        # Гарантия из ТЗ: проверка не запускается второй раз параллельно самой
        # себе — это должно быть верно независимо от того, что run-now
        # застал пробу "на лету".
        assert spy.max_concurrent == 1

        # А поставленный run-now запрос не теряется молча: следом обязательно
        # идёт ещё один прогон.
        await _wait_until(lambda: spy.calls >= 2)
    finally:
        await scheduler.shutdown()


async def test_trigger_now_on_paused_check_runs_once_without_scheduling(monkeypatch) -> None:
    spy = ProbeSpy(delay=0.01)
    monkeypatch.setattr("app.scheduler.engine.probe", spy)
    check = await _create_check(is_paused=True)

    scheduler = Scheduler(TestSessionLocal)  # чек на паузе, в расписание не добавляем
    result = await scheduler.trigger_now(check.id)

    assert result is not None
    assert result.success is True
    assert spy.calls == 1


async def test_trigger_now_on_paused_check_serializes_concurrent_calls(monkeypatch) -> None:
    spy = ProbeSpy(delay=0.1)
    monkeypatch.setattr("app.scheduler.engine.probe", spy)
    check = await _create_check(is_paused=True)

    scheduler = Scheduler(TestSessionLocal)
    results = await asyncio.gather(
        scheduler.trigger_now(check.id),
        scheduler.trigger_now(check.id),
    )

    assert all(r is not None for r in results)
    assert spy.calls == 2
    assert spy.max_concurrent == 1  # двойной клик не запускает пробы параллельно


async def test_remove_stops_further_probes(monkeypatch) -> None:
    spy = ProbeSpy(delay=0.01)
    monkeypatch.setattr("app.scheduler.engine.probe", spy)
    check = await _create_check(interval_seconds=30)

    scheduler = Scheduler(TestSessionLocal)
    scheduler.add(check)
    await _wait_until(lambda: spy.calls >= 1)

    await scheduler.remove(check.id)
    calls_after_remove = spy.calls
    await asyncio.sleep(0.1)

    assert spy.calls == calls_after_remove
