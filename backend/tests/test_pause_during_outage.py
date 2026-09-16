import datetime as dt

import pytest

from app.alerting.dispatcher import AlertDispatcher
from app.alerting.email_sender import FakeEmailSender
from app.incidents import make_incident_evaluator
from tests.conftest import TestSessionLocal
from tests.factories import create_check, create_group, incidents_for, load_check, record_result, sent_subjects

pytestmark = pytest.mark.asyncio


async def test_pausing_a_down_check_stops_the_outage_clock_and_shows_paused(client) -> None:
    group = await create_group(name="Prod", emails=("ops@example.com",))
    # Создаём напрямую в БД уже после старта тестового планировщика — он её не
    # подхватит и не будет гонять реальные пробы, результаты подаём руками.
    check = await create_check(group_id=group.id, is_paused=False, is_public=True)
    evaluate = make_incident_evaluator(TestSessionLocal)
    now = dt.datetime.now(dt.timezone.utc)
    last_failure = now - dt.timedelta(seconds=30)
    for when in (now - dt.timedelta(seconds=60), last_failure):
        result = await record_result(check.id, False, when)
        await evaluate(await load_check(check.id), result)

    dispatcher = AlertDispatcher(TestSessionLocal, FakeEmailSender(TestSessionLocal))
    await dispatcher.run_once()
    assert await sent_subjects() == ["[DOWN] site"]

    response = await client.post(f"/api/checks/{check.id}/pause")
    assert response.status_code == 200

    [incident] = await incidents_for(check.id)
    assert incident.ended_at == last_failure
    assert incident.end_reason == "paused"

    public = (await client.get("/api/public/status")).json()
    [prod] = public["groups"]
    [entry] = prod["checks"]
    assert entry["status"] == "paused"
    assert entry["current_downtime_seconds"] is None
    assert prod["status"] == "up"

    admin = next(s for s in (await client.get("/api/checks/status")).json() if s["check_id"] == check.id)
    assert admin["is_down"] is False

    # Пока проверка на паузе, никто не наблюдал восстановление — "RECOVERED" слать рано.
    await dispatcher.run_once()
    assert await sent_subjects() == ["[DOWN] site"]
