from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerting.email_sender import EmailSender
from app.maintenance import is_in_maintenance
from app.models.check import Check
from app.models.group import GroupAlertEmail
from app.models.incident import Incident

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 20


class AlertDispatcher:
    """Периодически сканирует инциденты, которым ещё не отправлено письмо
    (down или recovered), и досылает его — если сейчас нет активного окна
    обслуживания для этого чека/группы. Пока окно активно, инцидент просто
    остаётся необработанным и будет подхвачен одним из следующих проходов —
    в частности сразу после окончания окна, если падение всё ещё длится."""

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
            pending_down = (
                await db.execute(select(Incident).where(Incident.alert_down_sent_at.is_(None)))
            ).scalars().all()
            for incident in pending_down:
                await self._process(db, incident, kind="down", now=now)

            pending_recovered = (
                await db.execute(
                    select(Incident).where(
                        Incident.ended_at.is_not(None), Incident.alert_recovered_sent_at.is_(None)
                    )
                )
            ).scalars().all()
            for incident in pending_recovered:
                await self._process(db, incident, kind="recovered", now=now)

    async def _process(self, db: AsyncSession, incident: Incident, kind: str, now: dt.datetime) -> None:
        check = await db.get(Check, incident.check_id)
        if check is None:
            return
        if await is_in_maintenance(db, check, now):
            return

        recipients: list[str] = []
        if check.group_id is not None:
            result = await db.execute(
                select(GroupAlertEmail.email).where(GroupAlertEmail.group_id == check.group_id)
            )
            recipients = [row[0] for row in result.all()]

        if kind == "down":
            subject = f"[DOWN] {check.name}"
            body = f"{check.name} ({check.url}) не отвечает с {incident.started_at.isoformat()}."
        else:
            duration = incident.ended_at - incident.started_at  # type: ignore[operator]
            subject = f"[RECOVERED] {check.name}"
            body = f"{check.name} ({check.url}) снова доступен. Падение длилось {duration}."

        for email in recipients:
            await self._email_sender.send(to=email, subject=subject, body=body)

        if kind == "down":
            incident.alert_down_sent_at = now
        else:
            incident.alert_recovered_sent_at = now
        await db.commit()
