from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.check import Check
from app.models.check_result import CheckResult
from app.models.incident import Incident

# Кратковременный единичный сбой не считается падением — порог фиксирован на
# уровне приложения (см. DECISIONS.md, "Порог инцидента").
INCIDENT_THRESHOLD = 2


def make_incident_evaluator(
    session_factory: async_sessionmaker,
) -> Callable[[Check, CheckResult], Awaitable[None]]:
    """Возвращает callback для Scheduler(on_result=...): после каждой пробы
    решает, нужно ли открыть/закрыть инцидент. Не полагается ни на какое
    состояние в памяти — вся история берётся из БД, поэтому корректно
    переживает перезапуск сервера (открытый на момент остановки инцидент
    остаётся открытым и решается первым же новым результатом)."""

    async def evaluate(check: Check, result: CheckResult) -> None:
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
                return

            if open_incident is not None:
                return  # уже падает, ждём восстановления

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
                db.add(Incident(check_id=check.id, started_at=started_at))
                await db.commit()

    return evaluate
