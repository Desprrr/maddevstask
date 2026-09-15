import datetime as dt

import pytest

pytestmark = pytest.mark.asyncio


def _iso(d: dt.datetime) -> str:
    return d.isoformat()


NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


async def test_create_window_for_check(client) -> None:
    check = (
        await client.post("/api/checks", json={"name": "c", "url": "http://127.0.0.1:9"})
    ).json()

    response = await client.post(
        "/api/maintenance-windows",
        json={
            "check_id": check["id"],
            "starts_at": _iso(NOW),
            "ends_at": _iso(NOW + dt.timedelta(hours=1)),
            "note": "planned",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["check_id"] == check["id"]
    assert body["group_id"] is None


async def test_create_window_for_group(client) -> None:
    group = (await client.post("/api/groups", json={"name": "g"})).json()

    response = await client.post(
        "/api/maintenance-windows",
        json={
            "group_id": group["id"],
            "starts_at": _iso(NOW),
            "ends_at": _iso(NOW + dt.timedelta(hours=1)),
        },
    )
    assert response.status_code == 201
    assert response.json()["group_id"] == group["id"]


async def test_create_window_requires_exactly_one_target(client) -> None:
    both = await client.post(
        "/api/maintenance-windows",
        json={"check_id": 1, "group_id": 1, "starts_at": _iso(NOW), "ends_at": _iso(NOW + dt.timedelta(hours=1))},
    )
    assert both.status_code == 422

    neither = await client.post(
        "/api/maintenance-windows",
        json={"starts_at": _iso(NOW), "ends_at": _iso(NOW + dt.timedelta(hours=1))},
    )
    assert neither.status_code == 422


async def test_create_window_invalid_date_range_rejected(client) -> None:
    response = await client.post(
        "/api/maintenance-windows",
        json={"check_id": 1, "starts_at": _iso(NOW), "ends_at": _iso(NOW)},
    )
    assert response.status_code == 422


async def test_create_window_missing_check_404(client) -> None:
    response = await client.post(
        "/api/maintenance-windows",
        json={
            "check_id": 999999,
            "starts_at": _iso(NOW),
            "ends_at": _iso(NOW + dt.timedelta(hours=1)),
        },
    )
    assert response.status_code == 404


async def test_list_filters_and_delete(client) -> None:
    check = (
        await client.post("/api/checks", json={"name": "c", "url": "http://127.0.0.1:9"})
    ).json()
    created = await client.post(
        "/api/maintenance-windows",
        json={
            "check_id": check["id"],
            "starts_at": _iso(NOW),
            "ends_at": _iso(NOW + dt.timedelta(hours=1)),
        },
    )
    window_id = created.json()["id"]

    listed = await client.get("/api/maintenance-windows", params={"check_id": check["id"]})
    assert len(listed.json()) == 1

    delete_response = await client.delete(f"/api/maintenance-windows/{window_id}")
    assert delete_response.status_code == 204

    listed_after = await client.get("/api/maintenance-windows", params={"check_id": check["id"]})
    assert listed_after.json() == []
