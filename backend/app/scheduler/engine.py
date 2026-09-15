from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.check import Check
from app.models.check_result import CheckResult
from app.scheduler.prober import probe

logger = logging.getLogger(__name__)

OnResult = Callable[[Check, CheckResult], Awaitable[None]]


class _CheckState:
    __slots__ = ("trigger", "run_done", "last_result", "task", "manual_lock")

    def __init__(self) -> None:
        self.trigger = asyncio.Event()
        self.run_done = asyncio.Event()
        self.last_result: CheckResult | None = None
        self.task: asyncio.Task[None] | None = None
        self.manual_lock = asyncio.Lock()


class Scheduler:
    """Один asyncio.Task на активный check. Следующий запуск планируется от
    момента завершения предыдущего (не по фиксированной сетке) — это и есть
    гарантия "проверка не запускается второй раз параллельно самой себе",
    даже если проба длилась дольше своего interval_seconds."""

    def __init__(self, session_factory: async_sessionmaker, on_result: OnResult | None = None) -> None:
        self._session_factory = session_factory
        self._on_result = on_result
        self._states: dict[int, _CheckState] = {}
        self._manual_locks: dict[int, asyncio.Lock] = {}

    async def start(self) -> None:
        async with self._session_factory() as db:
            result = await db.execute(select(Check).where(Check.is_paused.is_(False)))
            checks = result.scalars().all()
        for check in checks:
            self.add(check)

    async def shutdown(self) -> None:
        for check_id in list(self._states.keys()):
            await self.remove(check_id)

    def add(self, check: Check) -> None:
        if check.id in self._states:
            return
        state = _CheckState()
        self._states[check.id] = state
        state.task = asyncio.create_task(self._loop(check.id))

    async def remove(self, check_id: int) -> None:
        state = self._states.pop(check_id, None)
        if state is not None and state.task is not None:
            state.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state.task

    async def resume(self, check_id: int) -> None:
        if check_id in self._states:
            return
        check = await self._load_check(check_id)
        if check is not None and not check.is_paused:
            self.add(check)

    async def restart(self, check_id: int) -> None:
        """Пересоздаёт task с текущими данными из БД — используется после
        редактирования чека, чтобы новый interval/url/timeout вступили в силу
        сразу, а не только со следующего случайного цикла."""
        await self.remove(check_id)
        await self.resume(check_id)

    async def trigger_now(self, check_id: int) -> CheckResult | None:
        state = self._states.get(check_id)
        if state is not None:
            state.run_done.clear()
            state.trigger.set()
            check = await self._load_check(check_id)
            timeout = (check.timeout_ms / 1000 + 5) if check else 15
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(state.run_done.wait(), timeout=timeout)
            return state.last_result

        # Чек не запланирован (на паузе) — разовая проба без постановки в
        # расписание. Лок по check_id всё равно защищает от параллельного
        # запуска, если по "run now" кликнули дважды подряд.
        lock = self._manual_locks.setdefault(check_id, asyncio.Lock())
        async with lock:
            check = await self._load_check(check_id)
            if check is None:
                return None
            return await self._run_once(check)

    async def _load_check(self, check_id: int) -> Check | None:
        async with self._session_factory() as db:
            return await db.get(Check, check_id)

    async def _run_once(self, check: Check) -> CheckResult:
        outcome = await probe(check)
        async with self._session_factory() as db:
            result = CheckResult(
                check_id=check.id,
                success=outcome.success,
                response_time_ms=outcome.response_time_ms,
                status_code=outcome.status_code,
                error=outcome.error,
            )
            db.add(result)
            await db.commit()
            await db.refresh(result)

        if self._on_result is not None:
            try:
                await self._on_result(check, result)
            except Exception:  # noqa: BLE001 - проба не должна падать из-за побочного эффекта
                logger.exception("on_result callback failed for check_id=%s", check.id)

        return result

    async def _loop(self, check_id: int) -> None:
        state = self._states[check_id]
        try:
            while True:
                # Важно: очищаем trigger ДО пробы, а не после. Если очищать
                # после, запрос "run now", выставленный, пока проба уже
                # выполняется, молча терялся бы (см. DECISIONS.md) — чек мог
                # бы просидеть без реакции целый interval. Так — trigger,
                # выставленный в любой момент цикла, гарантированно вызывает
                # новый прогон не позже чем сразу после текущего.
                state.trigger.clear()

                check = await self._load_check(check_id)
                if check is None:
                    return

                state.last_result = await self._run_once(check)
                state.run_done.set()

                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(state.trigger.wait(), timeout=check.interval_seconds)
        except asyncio.CancelledError:
            raise
