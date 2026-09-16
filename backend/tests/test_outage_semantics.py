"""Сквозные сценарии "проба -> инцидент -> письмо" вокруг окон обслуживания,
простоя самого сервера мониторинга и паузы проверки. Каждый тест прогоняет
результаты через настоящий incident-эвалуатор и настоящий AlertDispatcher,
время подставляется явно — без sleep и без сети."""

import datetime as dt

import pytest

from app.alerting.dispatcher import AlertDispatcher
from app.alerting.email_sender import FakeEmailSender
from app.incidents import make_incident_evaluator
from tests.conftest import TestSessionLocal
from tests.factories import (
    add_window,
    create_check,
    create_group,
    incidents_for,
    load_check,
    record_result,
    sent_emails,
    sent_subjects,
)

pytestmark = pytest.mark.asyncio

T = dt.datetime(2026, 1, 1, 10, 0, tzinfo=dt.timezone.utc)


def at(minutes: float = 0, hours: float = 0) -> dt.datetime:
    return T + dt.timedelta(hours=hours, minutes=minutes)


class Monitor:
    def __init__(self, check_id: int) -> None:
        self.check_id = check_id
        self.evaluate = make_incident_evaluator(TestSessionLocal)
        self.dispatcher = AlertDispatcher(TestSessionLocal, FakeEmailSender(TestSessionLocal))

    async def probe(self, success: bool, when: dt.datetime):
        result = await record_result(self.check_id, success, when)
        return await self.evaluate(await load_check(self.check_id), result)

    async def sweep(self, when: dt.datetime) -> None:
        await self.dispatcher.run_once(now=when)


async def _monitored_check(**overrides) -> Monitor:
    group = await create_group(emails=("ops@example.com",))
    check = await create_check(**{"group_id": group.id, "is_paused": False, **overrides})
    return Monitor(check.id)


# --- окна обслуживания -------------------------------------------------------


async def test_outage_entirely_inside_maintenance_window_sends_no_emails() -> None:
    m = await _monitored_check()
    await add_window(at(0), at(hours=1), check_id=m.check_id)

    await m.probe(False, at(10))
    await m.probe(False, at(10.5))
    await m.sweep(at(10.6))
    await m.probe(True, at(11))
    await m.sweep(at(11.1))

    await m.sweep(at(hours=1, minutes=5))  # окно закончилось, сайт давно в порядке

    assert await sent_subjects() == []


async def test_outage_still_ongoing_when_window_ends_is_reported() -> None:
    m = await _monitored_check()
    await add_window(at(0), at(51), check_id=m.check_id)

    await m.probe(False, at(50))
    await m.probe(False, at(50.5))
    await m.sweep(at(50.6))
    assert await sent_subjects() == []

    await m.probe(False, at(51))
    await m.sweep(at(51.2))  # окно только что закончилось, сайт всё ещё лежит
    assert await sent_subjects() == ["[DOWN] site"]


async def test_outage_opened_and_closed_between_two_sweeps_still_gets_both_emails() -> None:
    m = await _monitored_check()

    await m.probe(False, at(0))
    await m.probe(False, at(0.5))
    await m.probe(True, at(0.6))  # "проверить сейчас" сразу после открытия инцидента
    await m.sweep(at(1))

    assert await sent_subjects() == ["[DOWN] site", "[RECOVERED] site"]


# --- простой самого сервера мониторинга --------------------------------------


async def test_failures_separated_by_monitor_downtime_do_not_form_a_streak() -> None:
    m = await _monitored_check()

    await m.probe(False, at(0))
    await m.probe(False, at(hours=2))  # между ними сервер мониторинга лежал

    assert await incidents_for(m.check_id) == []


async def test_open_incident_is_closed_at_last_result_before_monitor_downtime() -> None:
    m = await _monitored_check()
    await m.probe(False, at(0))
    await m.probe(False, at(0.5))

    await m.probe(False, at(hours=2))
    [interrupted] = await incidents_for(m.check_id)
    assert interrupted.ended_at == at(0.5)
    assert interrupted.end_reason == "monitoring_gap"

    await m.probe(False, at(hours=2, minutes=0.5))
    first, second = await incidents_for(m.check_id)
    assert second.started_at == at(hours=2)
    assert second.ended_at is None


async def test_monitor_restart_mid_outage_does_not_send_a_second_down() -> None:
    m = await _monitored_check()
    await m.probe(False, at(0))
    await m.probe(False, at(0.5))
    await m.sweep(at(1))

    await m.probe(False, at(hours=2))
    await m.probe(False, at(hours=2, minutes=0.5))
    await m.sweep(at(hours=2, minutes=1))
    await m.probe(True, at(hours=2, minutes=1.5))
    await m.sweep(at(hours=2, minutes=2))

    assert await sent_subjects() == ["[DOWN] site", "[RECOVERED] site"]


async def test_site_found_up_after_monitor_restart_gets_recovered_without_counting_downtime() -> None:
    m = await _monitored_check()
    await m.probe(False, at(0))
    await m.probe(False, at(0.5))
    await m.sweep(at(1))

    await m.probe(True, at(hours=2))
    await m.sweep(at(hours=2, minutes=1))

    [incident] = await incidents_for(m.check_id)
    assert incident.ended_at == at(0.5)
    assert await sent_subjects() == ["[DOWN] site", "[RECOVERED] site"]


async def test_single_failure_after_restart_then_recovery_still_closes_the_loop() -> None:
    m = await _monitored_check()
    await m.probe(False, at(0))
    await m.probe(False, at(0.5))
    await m.sweep(at(1))

    await m.probe(False, at(hours=2))
    await m.sweep(at(hours=2, minutes=0.2))
    assert await sent_subjects() == ["[DOWN] site"]  # последняя проба — сбой, рано говорить "восстановился"

    await m.probe(True, at(hours=2, minutes=0.5))
    await m.sweep(at(hours=2, minutes=1))
    assert await sent_subjects() == ["[DOWN] site", "[RECOVERED] site"]


async def test_unnotified_incident_interrupted_by_restart_is_reported_from_the_new_start() -> None:
    m = await _monitored_check()
    await m.probe(False, at(0))
    await m.probe(False, at(0.5))  # инцидент открылся, но sweep не успел до остановки сервера

    await m.probe(False, at(hours=2))
    await m.probe(False, at(hours=2, minutes=0.5))
    await m.sweep(at(hours=2, minutes=1))

    [email] = await sent_emails()
    assert email.subject == "[DOWN] site"
    assert at(hours=2).isoformat() in email.body


# --- пауза -------------------------------------------------------------------


async def test_probes_of_a_paused_check_never_open_incidents() -> None:
    m = await _monitored_check(is_paused=True)  # например, "проверить сейчас" на паузе

    await m.probe(False, at(0))
    await m.probe(False, at(0.5))

    assert await incidents_for(m.check_id) == []
