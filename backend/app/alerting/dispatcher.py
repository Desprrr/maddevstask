from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerting.email_sender import EmailSender
from app.maintenance import is_in_maintenance, maintenance_overlaps
from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.group import GroupAlertEmail
from app.models.incident import END_RECOVERED, Incident

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 20


class AlertDispatcher:
    """Периодический sweep писем. Письма описывают то, что думают получатели,
    а не каждый инцидент журнала: `Check.down_notified` = "им сказано, что сайт
    лежит". Отсюда три правила за проход:

    1. Открытый инцидент, получатели ещё не в курсе, окна нет — DOWN.
    2. Закрытый инцидент, о котором никто не узнал: если закрылся восстановлением
       и не пересекался с окном обслуживания (просто быстро прошёл между sweep'ами)
       — DOWN и RECOVERED парой; иначе (целиком внутри окна, прерван простоем
       мониторинга или паузой) — пометить и молчать.
    3. Получателям сказано "лежит", открытых инцидентов нет, последняя проба
       успешна, окна нет — RECOVERED.

    Поэтому простой мониторинга посреди падения даёт два инцидента в журнале, но
    одно DOWN и одно RECOVERED; а падение внутри окна — ни одного письма."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        email_sender: EmailSender,
        sweep_interval: float = SWEEP_INTERVAL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._email_sender = email_sender
        self._sweep_interval = sweep_interval
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - один неудачный проход не должен убивать sweep навсегда
                logger.exception("alert sweep failed")
            await asyncio.sleep(self._sweep_interval)

    async def run_once(self, now: dt.datetime | None = None) -> None:
        now = now or dt.datetime.now(dt.timezone.utc)
        async with self._session_factory() as db:
            await self._notify_new_outages(db, now)
            await self._settle_unnotified_closed_incidents(db, now)
            await self._notify_recoveries(db, now)

    async def _notify_new_outages(self, db: AsyncSession, now: dt.datetime) -> None:
        rows = await db.execute(
            select(Incident, Check)
            .join(Check, Check.id == Incident.check_id)
            .where(
                Incident.ended_at.is_(None),
                Incident.alert_down_sent_at.is_(None),
                Check.down_notified.is_(False),
            )
            .order_by(Incident.started_at)
        )
        for incident, check in rows.all():
            if await is_in_maintenance(db, check, now):
                continue
            await self._send(db, check, *_down_email(check, incident))
            incident.alert_down_sent_at = now
            check.down_notified = True
            await db.commit()

    async def _settle_unnotified_closed_incidents(self, db: AsyncSession, now: dt.datetime) -> None:
        rows = await db.execute(
            select(Incident, Check)
            .join(Check, Check.id == Incident.check_id)
            .where(
                Incident.ended_at.is_not(None),
                Incident.alert_down_sent_at.is_(None),
                Incident.alert_recovered_sent_at.is_(None),
                Incident.notifications_skipped.is_(False),
                Check.down_notified.is_(False),
            )
            .order_by(Incident.started_at)
        )
        for incident, check in rows.all():
            recovered = incident.end_reason in (None, END_RECOVERED)
            if not recovered or await maintenance_overlaps(db, check, incident.started_at, incident.ended_at):
                incident.notifications_skipped = True
                await db.commit()
                continue
            if await is_in_maintenance(db, check, now):
                continue
            await self._send(db, check, *_down_email(check, incident))
            await self._send(db, check, *_recovered_email(check, incident))
            incident.alert_down_sent_at = now
            incident.alert_recovered_sent_at = now
            await db.commit()

    async def _notify_recoveries(self, db: AsyncSession, now: dt.datetime) -> None:
        checks = (await db.execute(select(Check).where(Check.down_notified.is_(True)))).scalars().all()
        for check in checks:
            still_open = (
                await db.execute(
                    select(Incident.id).where(Incident.check_id == check.id, Incident.ended_at.is_(None))
                )
            ).first()
            if still_open is not None:
                continue
            latest_success = (
                await db.execute(
                    select(CheckResult.success)
                    .where(CheckResult.check_id == check.id)
                    .order_by(CheckResult.checked_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if not latest_success:  # проб нет или последняя — сбой (например, серия ещё не дотянула до порога)
                continue
            if await is_in_maintenance(db, check, now):
                continue

            last_incident = (
                await db.execute(
                    select(Incident)
                    .where(Incident.check_id == check.id)
                    .order_by(Incident.started_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            await self._send(db, check, *_recovered_email(check, last_incident))
            if last_incident is not None and last_incident.alert_recovered_sent_at is None:
                last_incident.alert_recovered_sent_at = now
            check.down_notified = False
            await db.commit()

    async def _send(self, db: AsyncSession, check: Check, subject: str, body: str) -> None:
        if check.group_id is None:
            return
        result = await db.execute(
            select(GroupAlertEmail.email).where(GroupAlertEmail.group_id == check.group_id)
        )
        for (email,) in result.all():
            await self._email_sender.send(to=email, subject=subject, body=body)


def _down_email(check: Check, incident: Incident) -> tuple[str, str]:
    return (
        f"[DOWN] {check.name}",
        f"{check.name} ({check.url}) не отвечает с {incident.started_at.isoformat()}.",
    )


def _recovered_email(check: Check, incident: Incident | None) -> tuple[str, str]:
    body = f"{check.name} ({check.url}) снова доступен."
    if incident is not None and incident.ended_at is not None:
        duration = incident.ended_at - incident.started_at
        if incident.end_reason in (None, END_RECOVERED):
            body += f" Падение длилось {duration}."
        else:
            body += (
                f" Наблюдаемое падение длилось {duration}; мониторинг прерывался, "
                "поэтому точный момент восстановления неизвестен."
            )
    return f"[RECOVERED] {check.name}", body
