import datetime as dt

import pytest

from app.incidents import IncidentEvent
from app.models.check import Check
from app.models.check_result import CheckResult
from app.realtime.connection_manager import ConnectionManager

pytestmark = pytest.mark.asyncio


class FakeWebSocket:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        if self.fail:
            raise RuntimeError("connection is dead")
        self.messages.append(payload)


def _check(is_public: bool) -> Check:
    return Check(
        id=1,
        group_id=None,
        name="c",
        url="http://unused.invalid",
        interval_seconds=30,
        timeout_ms=5000,
        expected_status_code=200,
        is_public=is_public,
    )


def _result() -> CheckResult:
    return CheckResult(
        id=1,
        check_id=1,
        checked_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        success=True,
        response_time_ms=10,
        status_code=200,
        error=None,
    )


async def test_admin_always_receives_check_result() -> None:
    manager = ConnectionManager()
    admin_ws = FakeWebSocket()
    manager._admin.add(admin_ws)  # noqa: SLF001 - тест внутренней механики рассылки

    await manager.broadcast_check_result(_check(is_public=False), _result())

    assert len(admin_ws.messages) == 1
    assert admin_ws.messages[0]["type"] == "check.result"


async def test_public_only_receives_public_checks() -> None:
    manager = ConnectionManager()
    public_ws = FakeWebSocket()
    manager._public.add(public_ws)  # noqa: SLF001

    await manager.broadcast_check_result(_check(is_public=False), _result())
    assert public_ws.messages == []

    await manager.broadcast_check_result(_check(is_public=True), _result())
    assert len(public_ws.messages) == 1


async def test_incident_event_payload_shape() -> None:
    manager = ConnectionManager()
    admin_ws = FakeWebSocket()
    manager._admin.add(admin_ws)  # noqa: SLF001

    event = IncidentEvent(
        kind="opened",
        incident_id=42,
        started_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        ended_at=None,
    )
    await manager.broadcast_incident_event(_check(is_public=False), event)

    assert admin_ws.messages[0] == {
        "type": "incident.opened",
        "check_id": 1,
        "group_id": None,
        "incident_id": 42,
        "started_at": "2026-01-01T00:00:00+00:00",
        "ended_at": None,
    }


async def test_dead_connection_is_dropped_without_blocking_others() -> None:
    manager = ConnectionManager()
    dead = FakeWebSocket(fail=True)
    alive = FakeWebSocket()
    manager._admin.add(dead)  # noqa: SLF001
    manager._admin.add(alive)  # noqa: SLF001

    await manager.broadcast_check_result(_check(is_public=False), _result())

    assert len(alive.messages) == 1
    assert dead not in manager._admin  # noqa: SLF001
