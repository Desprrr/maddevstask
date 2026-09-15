import pytest

pytestmark = pytest.mark.asyncio


async def test_create_and_get_group(client) -> None:
    response = await client.post(
        "/api/groups",
        json={"name": "Prod", "alert_emails": ["ops@example.com"]},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Prod"
    assert body["alert_emails"] == ["ops@example.com"]

    group_id = body["id"]
    get_response = await client.get(f"/api/groups/{group_id}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == group_id


async def test_get_missing_group_404(client) -> None:
    response = await client.get("/api/groups/999999")
    assert response.status_code == 404


async def test_list_groups(client) -> None:
    await client.post("/api/groups", json={"name": "A"})
    await client.post("/api/groups", json={"name": "B"})

    response = await client.get("/api/groups")
    assert response.status_code == 200
    names = {g["name"] for g in response.json()}
    assert names == {"A", "B"}


async def test_update_group_replaces_alert_emails(client) -> None:
    created = await client.post(
        "/api/groups", json={"name": "Prod", "alert_emails": ["old@example.com"]}
    )
    group_id = created.json()["id"]

    updated = await client.patch(
        f"/api/groups/{group_id}",
        json={"alert_emails": ["new1@example.com", "new2@example.com"]},
    )
    assert updated.status_code == 200
    assert sorted(updated.json()["alert_emails"]) == ["new1@example.com", "new2@example.com"]


async def test_delete_group_ungroups_its_checks(client) -> None:
    group = (await client.post("/api/groups", json={"name": "Temp"})).json()
    check = (
        await client.post(
            "/api/checks",
            json={"name": "site", "url": "http://127.0.0.1:9", "group_id": group["id"]},
        )
    ).json()

    delete_response = await client.delete(f"/api/groups/{group['id']}")
    assert delete_response.status_code == 204

    check_after = (await client.get(f"/api/checks/{check['id']}")).json()
    assert check_after["group_id"] is None
