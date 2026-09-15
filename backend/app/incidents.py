from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.incident import Incident

# Кратковременный единичный сбой не считается падением — порог фиксирован на
# уровне приложения (см. DECISIONS.md, "Порог инцидента").
INCIDENT_THRESHOLD = 2


@dataclass(frozen=True)
class IncidentEvent:
    kind: str  # "opened" | "closed"
    incident_id: int
    started_at: dt.datetime
    ended_at: dt.datetime | None


def make_incident_evaluator(
    session_factory: async_sessionmaker,
) -> Callable[[Check, CheckResult], Awaitable[IncidentEvent | None]]:
    """Возвращает callback для Scheduler(on_result=...): после каждой пробы
    решает, нужно ли открыть/закрыть инцидент, и возвращает описание
    случившегося перехода (для WS-рассылки) или None, если ничего не
    изменилось. Не полагается ни на какое состояние в памяти — вся история
    берётся из БД, поэтому корректно переживает перезапуск сервера (открытый
    на момент остановки инцидент остаётся открытым и решается первым же
    новым результатом)."""

    async def evaluate(check: Check, result: CheckResult) -> IncidentEvent | None:
        async with session_factory() as db:
            open_incident = (
                await db.execute(
                    select(Incident).where(Incident.check_id == check.id, Incident.ended_at.is_(None))
                )
            ).scalar_one_or_none()

            if result.success:
                if open_incident is not None:
                    open_incident.ended_at = result.checked_at
                    await db.commit()
                    return IncidentEvent(
                        "closed", open_incident.id, open_incident.started_at, open_incident.ended_at
                    )
                return None

            if open_incident is not None:
                return None  # уже падает, ждём восстановления

            recent = (
                await db.execute(
                    select(CheckResult)
                    .where(CheckResult.check_id == check.id)
                    .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
                    .limit(INCIDENT_THRESHOLD)
                )
            ).scalars().all()

            if len(recent) >= INCIDENT_THRESHOLD and all(not r.success for r in recent):
                started_at = recent[-1].checked_at  # самый ранний из серии сбоев
                incident = Incident(check_id=check.id, started_at=started_at)
                db.add(incident)
                await db.commit()
                await db.refresh(incident)
                return IncidentEvent("opened", incident.id, incident.started_at, None)

            return None

    return evaluate
