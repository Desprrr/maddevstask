"""Панель статусов и публичная страница не должны деградировать с ростом
истории. Вместо замеров времени (нестабильны в CI) проверяем детерминированно:
перехватываем SQL, который реально выполняют эндпоинты, и через EXPLAIN ANALYZE
считаем, сколько строк `check_results` читает запрос "последний результат на
проверку". Должно быть порядка числа проверок, а не размера истории."""

import datetime as dt
import json
import random
import time

import asyncpg
import pytest
from sqlalchemy import event

from tests.conftest import test_engine
from tests.factories import create_check

pytestmark = pytest.mark.asyncio

CHECKS = 50
RESULTS_PER_CHECK = 2000
RAW_DSN = "postgresql://monitor:monitor@localhost:5432/monitor_test"


async def _seed_history(check_ids: list[int]) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    records = [
        (cid, now - dt.timedelta(minutes=5 * i), random.random() > 0.05, 50, 200, None)
        for cid in check_ids
        for i in range(RESULTS_PER_CHECK)
    ]
    conn = await asyncpg.connect(RAW_DSN, ssl=False)
    try:
        await conn.copy_records_to_table(
            "check_results",
            records=records,
            columns=["check_id", "checked_at", "success", "response_time_ms", "status_code", "error"],
        )
        await conn.execute("ANALYZE check_results")
    finally:
        await conn.close()


def _rows_read_from_check_results(plan_node: dict) -> int:
    total = 0
    if plan_node.get("Relation Name") == "check_results":
        total += plan_node["Actual Rows"] * plan_node["Actual Loops"]
    for child in plan_node.get("Plans", []):
        total += _rows_read_from_check_results(child)
    return total


async def _latest_result_rows_read(client, path: str) -> tuple[int, float]:
    captured: list[tuple[str, tuple]] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if "check_results" in statement and "checked_at DESC" in statement:
            captured.append((statement, tuple(parameters or ())))

    event.listen(test_engine.sync_engine, "before_cursor_execute", capture)
    try:
        started = time.monotonic()
        response = await client.get(path)
        elapsed = time.monotonic() - started
    finally:
        event.remove(test_engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert captured, f"{path}: не нашли запрос последнего результата"

    conn = await asyncpg.connect(RAW_DSN, ssl=False)
    try:
        rows_read = 0
        for statement, params in captured:
            plan_json = await conn.fetchval(f"EXPLAIN (ANALYZE, FORMAT JSON) {statement}", *params)
            plan = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
            rows_read += _rows_read_from_check_results(plan[0]["Plan"])
    finally:
        await conn.close()
    return rows_read, elapsed


@pytest.mark.parametrize("path", ["/api/checks/status", "/api/public/status"])
async def test_latest_result_lookup_does_not_scan_history(client, path) -> None:
    checks = [await create_check(name=f"c{i}", is_public=True) for i in range(CHECKS)]
    await _seed_history([c.id for c in checks])

    rows_read, elapsed = await _latest_result_rows_read(client, path)

    history_rows = CHECKS * RESULTS_PER_CHECK
    print(f"{path}: прочитано {rows_read} из {history_rows} строк истории, {elapsed * 1000:.0f} мс")
    assert rows_read <= 2 * CHECKS, (
        f"{path} прочитал {rows_read} строк check_results ради последнего результата "
        f"{CHECKS} проверок — время ответа будет расти вместе с историей"
    )
