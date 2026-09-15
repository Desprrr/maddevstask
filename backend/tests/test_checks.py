import pytest

pytestmark = pytest.mark.asyncio


async def test_create_check_minimal(client) -> None:
    response = await client.post("/api/checks", json={"name": "Example", "url": "http://example.com"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Example"
    assert body["interval_seconds"] == 60
    assert body["is_paused"] is False
    assert body["is_public"] is False


async def test_create_check_with_unknown_group_404(client) -> None:
    response = await client.post(
        "/api/checks", json={"name": "Example", "url": "http://example.com", "group_id": 999999}
    )
    assert response.status_code == 404


async def test_create_check_interval_out_of_range_rejected(client) -> None:
    response = await client.post(
        "/api/checks", json={"name": "Example", "url": "http://example.com", "interval_seconds": 10}
    )
    assert response.status_code == 422


async def test_update_check_partial(client) -> None:
    created = (
        await client.post("/api/checks", json={"name": "Example", "url": "http://example.com"})
    ).json()

    updated = await client.patch(f"/api/checks/{created['id']}", json={"timeout_ms": 9000})
    assert updated.status_code == 200
    body = updated.json()
    assert body["timeout_ms"] == 9000
    assert body["name"] == "Example"  # untouched fields survive a partial update


async def test_pause_and_resume_check(client) -> None:
    created = (
        await client.post("/api/checks", json={"name": "Example", "url": "http://example.com"})
    ).json()
    check_id = created["id"]

    paused = await client.post(f"/api/checks/{check_id}/pause")
    assert paused.json()["is_paused"] is True

    resumed = await client.post(f"/api/checks/{check_id}/resume")
    assert resumed.json()["is_paused"] is False


async def test_delete_check(client) -> None:
    created = (
        await client.post("/api/checks", json={"name": "Example", "url": "http://example.com"})
    ).json()

    delete_response = await client.delete(f"/api/checks/{created['id']}")
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/checks/{created['id']}")
    assert get_response.status_code == 404


async def test_list_checks_filtered_by_group(client) -> None:
    group = (await client.post("/api/groups", json={"name": "G1"})).json()
    await client.post(
        "/api/checks", json={"name": "grouped", "url": "http://example.com", "group_id": group["id"]}
    )
    await client.post("/api/checks", json={"name": "ungrouped", "url": "http://example.com"})

    response = await client.get("/api/checks", params={"group_id": group["id"]})
    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert names == ["grouped"]
