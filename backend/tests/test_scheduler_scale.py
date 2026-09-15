"""Автоматическая проверка утверждений из ТЗ про масштаб: "50 проверок с
интервалом 30 секунд не мешают друг другу и не тормозят интерфейс. Один
медленный сайт не задерживает проверки остальных." Раньше это проверялось
только разовым ручным нагрузочным скриптом (см. DECISIONS.md, запись про
50 проверок) — здесь то же самое как постоянный тест, часть CI.

Проба подменена управляемой заглушкой (как и в test_scheduler.py) — тест
проверяет конкурентность самого планировщика, а не сеть; реальную проверку
через `target-emulator` с реальным HTTP закрывает `docker-e2e` в CI."""

import asyncio
import time

import pytest

from app.models.check import Check
from app.scheduler.engine import Scheduler
from app.scheduler.prober import ProbeOutcome
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio

N = 50


class ProbeSpy:
    def __init__(self, delay: float = 0.1, hang_for_check_id: int | None = None) -> None:
        self.calls = 0
        self.concurrent = 0
        self.max_concurrent = 0
        self.delay = delay
        self.hang_for_check_id = hang_for_check_id
        self.completed_check_ids: set[int] = set()

    async def __call__(self, check: Check) -> ProbeOutcome:
        self.calls += 1
        self.concurrent += 1
        self.max_concurrent = max(self.max_concurrent, self.concurrent)
        try:
            if self.hang_for_check_id is not None and check.id == self.hang_for_check_id:
                await asyncio.sleep(3600)  # намеренно "зависший" сайт — не завершится в рамках теста
            else:
                await asyncio.sleep(self.delay)
        finally:
            self.concurrent -= 1
        self.completed_check_ids.add(check.id)
        return ProbeOutcome(success=True, response_time_ms=1, status_code=200, error=None)


async def _create_checks(n: int) -> list[Check]:
    async with TestSessionLocal() as db:
        checks = [
            Check(
                name=f"scale-{i}",
                url="http://unused.invalid",
                interval_seconds=30,
                timeout_ms=5000,
                expected_status_code=200,
            )
            for i in range(n)
        ]
        db.add_all(checks)
        await db.commit()
        for c in checks:
            await db.refresh(c)
        return checks


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError("condition not met in time")


async def test_50_checks_probe_concurrently_not_sequentially(monkeypatch) -> None:
    spy = ProbeSpy(delay=0.1)
    monkeypatch.setattr("app.scheduler.engine.probe", spy)

    checks = await _create_checks(N)
    scheduler = Scheduler(TestSessionLocal)
    try:
        started = time.monotonic()
        for check in checks:
            scheduler.add(check)

        await _wait_until(lambda: spy.calls >= N)
        elapsed = time.monotonic() - started

        # Последовательно это заняло бы 50 * 0.1с = 5с; при настоящей
        # конкурентности — на порядок быстрее. Порог даёт большой запас на
        # дрожание тайминга в CI, но чётко отличает "конкурентно" от
        # "по очереди".
        assert elapsed < 2.0, f"50 проверок отработали за {elapsed:.2f}с — похоже на последовательный запуск"
        assert spy.max_concurrent > 10, "пробы не пересекались по времени — это не конкурентная работа"
    finally:
        await scheduler.shutdown()


async def test_one_hung_check_does_not_delay_the_others(monkeypatch) -> None:
    checks = await _create_checks(N)
    hung_check = checks[0]

    spy = ProbeSpy(delay=0.05, hang_for_check_id=hung_check.id)
    monkeypatch.setattr("app.scheduler.engine.probe", spy)

    scheduler = Scheduler(TestSessionLocal)
    try:
        for check in checks:
            scheduler.add(check)

        other_ids = {c.id for c in checks if c.id != hung_check.id}
        await _wait_until(lambda: other_ids <= spy.completed_check_ids)

        assert hung_check.id not in spy.completed_check_ids
    finally:
        await scheduler.shutdown()
