"""Публичный WebSocket-канал: отдаёт не больше, чем публичный REST, и сообщает
публичной странице об изменении состава (проверку сделали публичной/приватной,
удалили, поставили на паузу, переименовали группу с публичными проверками)."""

import datetime as dt

import pytest

from app.incidents import IncidentEvent
from app.main import app
from app.models.check import Check
from app.models.check_result import CheckResult
from app.realtime.connection_manager import ConnectionManager

pytestmark = pytest.mark.asyncio

WHEN = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)

    def types(self) -> list[str]:
        return [m["type"] for m in self.messages]


def _public_check() -> Check:
    return Check(id=7, group_id=3, name="api", url="http://internal-api.local:8080/health", is_public=True)


async def test_public_check_result_carries_no_operational_details() -> None:
    manager = ConnectionManager()
    admin, public = FakeWebSocket(), FakeWebSocket()
    manager._admin.add(admin)  # noqa: SLF001
    manager._public.add(public)  # noqa: SLF001
    result = CheckResult(
        check_id=7,
        checked_at=WHEN,
        success=False,
        response_time_ms=None,
        status_code=None,
        error="connect to internal-db.local:5432 refused",
    )

    await manager.broadcast_check_result(_public_check(), result)

    assert public.messages == [{"type": "check.result", "check_id": 7, "checked_at": WHEN.isoformat()}]
    assert admin.messages[0]["error"] == "connect to internal-db.local:5432 refused"


async def test_public_incident_event_is_trimmed_to_what_public_rest_exposes() -> None:
    manager = ConnectionManager()
    public = FakeWebSocket()
    manager._public.add(public)  # noqa: SLF001

    await manager.broadcast_incident_event(_public_check(), IncidentEvent("opened", 42, WHEN, None))

    assert public.messages == [
        {"type": "incident.opened", "check_id": 7, "started_at": WHEN.isoformat(), "ended_at": None}
    ]


def _listen_public() -> FakeWebSocket:
    ws = FakeWebSocket()
    app.state.connection_manager._public.add(ws)  # noqa: SLF001
    return ws


async def test_public_check_lifecycle_pings_public_page(client) -> None:
    ws = _listen_public()

    created = (
        await client.post("/api/checks", json={"name": "api", "url": "http://127.0.0.1:9", "is_public": True})
    ).json()
    assert "public.changed" in ws.types()

    for action in (
        lambda: client.post(f"/api/checks/{created['id']}/pause"),
        lambda: client.post(f"/api/checks/{created['id']}/resume"),
        lambda: client.patch(f"/api/checks/{created['id']}", json={"is_public": False}),
        lambda: client.patch(f"/api/checks/{created['id']}", json={"is_public": True}),
        lambda: client.delete(f"/api/checks/{created['id']}"),
    ):
        ws.messages.clear()
        response = await action()
        assert response.status_code in (200, 204)
        assert "public.changed" in ws.types(), response.request.url


async def test_private_check_changes_do_not_ping_public_page(client) -> None:
    ws = _listen_public()

    created = (await client.post("/api/checks", json={"name": "internal", "url": "http://127.0.0.1:9"})).json()
    await client.patch(f"/api/checks/{created['id']}", json={"timeout_ms": 1000})
    await client.post(f"/api/checks/{created['id']}/pause")
    await client.delete(f"/api/checks/{created['id']}")

    assert ws.messages == []


async def test_group_changes_ping_public_page_only_if_group_has_public_checks(client) -> None:
    public_group = (await client.post("/api/groups", json={"name": "Prod"})).json()
    private_group = (await client.post("/api/groups", json={"name": "Internal"})).json()
    await client.post(
        "/api/checks",
        json={"name": "api", "url": "http://127.0.0.1:9", "is_public": True, "group_id": public_group["id"]},
    )
    await client.post("/api/checks", json={"name": "db", "url": "http://127.0.0.1:9", "group_id": private_group["id"]})
    ws = _listen_public()

    await client.patch(f"/api/groups/{private_group['id']}", json={"name": "Internal tools"})
    assert "public.changed" not in ws.types()

    await client.patch(f"/api/groups/{public_group['id']}", json={"name": "Production"})
    assert "public.changed" in ws.types()

    ws.messages.clear()
    await client.delete(f"/api/groups/{public_group['id']}")
    assert "public.changed" in ws.types()
