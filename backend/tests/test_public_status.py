import datetime as dt

import pytest

from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.group import Group
from app.models.incident import Incident
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _create_group(name: str) -> Group:
    async with TestSessionLocal() as db:
        group = Group(name=name)
        db.add(group)
        await db.commit()
        await db.refresh(group)
        return group


async def _create_check(is_public: bool, group_id: int | None = None, name: str = "c") -> Check:
    async with TestSessionLocal() as db:
        check = Check(
            name=name,
            url="http://127.0.0.1:9",
            group_id=group_id,
            interval_seconds=30,
            timeout_ms=5000,
            expected_status_code=200,
            is_paused=True,
            is_public=is_public,
        )
        db.add(check)
        await db.commit()
        await db.refresh(check)
        return check


async def _record_result(check_id: int, success: bool, checked_at: dt.datetime) -> None:
    async with TestSessionLocal() as db:
        db.add(
            CheckResult(
                check_id=check_id,
                success=success,
                checked_at=checked_at,
                response_time_ms=5 if success else None,
                status_code=200 if success else 500,
                error=None if success else "boom",
            )
        )
        await db.commit()


async def _create_incident(check_id: int, started_at: dt.datetime) -> None:
    async with TestSessionLocal() as db:
        db.add(Incident(check_id=check_id, started_at=started_at))
        await db.commit()


async def test_private_checks_are_never_exposed(client) -> None:
    await _create_check(is_public=False)

    response = await client.get("/api/public/status")
    assert response.json() == {"groups": []}


async def test_ungrouped_public_check_appears_with_null_group(client) -> None:
    check = await _create_check(is_public=True, name="solo")

    response = await client.get("/api/public/status")
    body = response.json()

    assert len(body["groups"]) == 1
    assert body["groups"][0]["group_id"] is None
    assert body["groups"][0]["name"] is None
    assert body["groups"][0]["checks"][0]["check_id"] == check.id
    assert body["groups"][0]["checks"][0]["status"] == "up"


async def test_group_status_is_down_if_any_public_check_is_down(client) -> None:
    group = await _create_group("Prod")
    ok_check = await _create_check(is_public=True, group_id=group.id, name="ok-service")
    down_check = await _create_check(is_public=True, group_id=group.id, name="down-service")
    await _create_incident(down_check.id, started_at=dt.datetime.now(dt.timezone.utc))

    response = await client.get("/api/public/status")
    body = response.json()
    group_entry = next(g for g in body["groups"] if g["group_id"] == group.id)

    assert group_entry["status"] == "down"
    assert group_entry["name"] == "Prod"
    statuses = {c["check_id"]: c["status"] for c in group_entry["checks"]}
    assert statuses[ok_check.id] == "up"
    assert statuses[down_check.id] == "down"


async def test_private_check_in_a_group_does_not_affect_public_group_status(client) -> None:
    group = await _create_group("Mixed")
    public_ok = await _create_check(is_public=True, group_id=group.id, name="public-ok")
    private_down = await _create_check(is_public=False, group_id=group.id, name="private-down")
    await _create_incident(private_down.id, started_at=dt.datetime.now(dt.timezone.utc))

    response = await client.get("/api/public/status")
    body = response.json()
    group_entry = next(g for g in body["groups"] if g["group_id"] == group.id)

    # приватный чек не должен даже появиться, и его падение не должно
    # утянуть публичный статус группы в "down"
    assert len(group_entry["checks"]) == 1
    assert group_entry["checks"][0]["check_id"] == public_ok.id
    assert group_entry["status"] == "up"


async def test_uptime_ratio_24h_excludes_older_data(client) -> None:
    check = await _create_check(is_public=True, name="c")
    now = dt.datetime.now(dt.timezone.utc)

    await _record_result(check.id, True, now - dt.timedelta(hours=1))
    await _record_result(check.id, False, now - dt.timedelta(hours=2))
    await _record_result(check.id, True, now - dt.timedelta(hours=30))  # за пределами 24ч — не считается

    response = await client.get("/api/public/status")
    body = response.json()
    entry = body["groups"][0]["checks"][0]
    assert entry["uptime_ratio_24h"] == pytest.approx(0.5)
