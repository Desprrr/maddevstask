from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.incident import END_MONITORING_GAP, END_PAUSED, END_RECOVERED, Incident

# Кратковременный единичный сбой не считается падением — порог фиксирован на
# уровне приложения (см. DECISIONS.md, "Порог инцидента").
INCIDENT_THRESHOLD = 2


@dataclass(frozen=True)
class IncidentEvent:
    kind: str  # "opened" | "closed"
    incident_id: int
    started_at: dt.datetime
    ended_at: dt.datetime | None


def monitoring_gap_threshold(check: Check) -> dt.timedelta:
    """Следующая проба стартует через interval после завершения предыдущей, а
    проба длится не дольше timeout — значит, соседние результаты в норме не дальше
    interval + timeout. Разрыв больше 2×interval + timeout означает, что проверку в
    это время никто не выполнял (сервер мониторинга лежал), а не что сайт падал."""
    return dt.timedelta(seconds=2 * check.interval_seconds + check.timeout_ms / 1000)


def _event(kind: str, incident: Incident) -> IncidentEvent:
    return IncidentEvent(kind, incident.id, incident.started_at, incident.ended_at)


async def _open_incident(db: AsyncSession, check_id: int) -> Incident | None:
    return (
        await db.execute(select(Incident).where(Incident.check_id == check_id, Incident.ended_at.is_(None)))
    ).scalar_one_or_none()


async def close_incident_for_pause(db: AsyncSession, check: Check) -> IncidentEvent | None:
    """При паузе проверки наблюдение прекращается: открытый инцидент закрываем
    временем последней пробы, чтобы длительность падения не росла, пока никто не
    смотрит. Коммит — на вызывающей стороне."""
    incident = await _open_incident(db, check.id)
    if incident is None:
        return None
    last_checked_at = (
        await db.execute(
            select(CheckResult.checked_at)
            .where(CheckResult.check_id == check.id)
            .order_by(CheckResult.checked_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    incident.ended_at = max(last_checked_at or incident.started_at, incident.started_at)
    incident.end_reason = END_PAUSED
    return _event("closed", incident)


def make_incident_evaluator(
    session_factory: async_sessionmaker,
) -> Callable[[Check, CheckResult], Awaitable[IncidentEvent | None]]:
    """Возвращает callback для Scheduler(on_result=...): после каждой пробы решает,
    открыть/закрыть ли инцидент, и возвращает случившийся переход (для WS) или None.
    Состояния в памяти нет — всё из БД, поэтому корректно переживает рестарт."""

    async def evaluate(check: Check, result: CheckResult) -> IncidentEvent | None:
        if check.is_paused:
            return None  # ручной "проверить сейчас" на паузе — диагностика, а не мониторинг

        gap = monitoring_gap_threshold(check)
        async with session_factory() as db:
            open_incident = await _open_incident(db, check.id)
            previous = (
                await db.execute(
                    select(CheckResult)
                    .where(CheckResult.check_id == check.id, CheckResult.checked_at < result.checked_at)
                    .order_by(CheckResult.checked_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            if open_incident is not None and previous is not None and result.checked_at - previous.checked_at > gap:
                # Что было с сайтом во время простоя мониторинга — неизвестно; падение
                # наблюдалось до последней пробы перед простоем, дальше — пробел.
                open_incident.ended_at = previous.checked_at
                open_incident.end_reason = END_MONITORING_GAP
                await db.commit()
                return _event("closed", open_incident)

            if result.success:
                if open_incident is None:
                    return None
                open_incident.ended_at = result.checked_at
                open_incident.end_reason = END_RECOVERED
                await db.commit()
                return _event("closed", open_incident)

            if open_incident is not None:
                return None

            recent = (
                await db.execute(
                    select(CheckResult)
                    .where(CheckResult.check_id == check.id, CheckResult.checked_at <= result.checked_at)
                    .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
                    .limit(INCIDENT_THRESHOLD)
                )
            ).scalars().all()
            if len(recent) < INCIDENT_THRESHOLD or any(r.success for r in recent):
                return None
            if any(newer.checked_at - older.checked_at > gap for newer, older in zip(recent, recent[1:])):
                return None  # сбои по разные стороны простоя мониторинга — не серия

            incident = Incident(check_id=check.id, started_at=recent[-1].checked_at)
            db.add(incident)
            await db.commit()
            await db.refresh(incident)
            return _event("opened", incident)

    return evaluate
