from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from app.incidents import IncidentEvent
from app.models.check import Check
from app.models.check_result import CheckResult

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Держит два независимых пула WebSocket-подключений — admin (видит все
    чеки) и public (видит только то, что владелец отметил как публичное).
    Рассылка идёт сразу после того, как результат/инцидент записан в БД, так
    что все открытые вкладки (админка и публичная страница) видят одно и то
    же без перезагрузки страницы."""

    def __init__(self) -> None:
        self._admin: set[WebSocket] = set()
        self._public: set[WebSocket] = set()

    async def connect_admin(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._admin.add(websocket)

    async def connect_public(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._public.add(websocket)

    def disconnect_admin(self, websocket: WebSocket) -> None:
        self._admin.discard(websocket)

    def disconnect_public(self, websocket: WebSocket) -> None:
        self._public.discard(websocket)

    async def broadcast_check_result(self, check: Check, result: CheckResult) -> None:
        payload = {
            "type": "check.result",
            "check_id": check.id,
            "group_id": check.group_id,
            "success": result.success,
            "response_time_ms": result.response_time_ms,
            "status_code": result.status_code,
            "error": result.error,
            "checked_at": result.checked_at.isoformat(),
        }
        await self._broadcast(self._admin, payload)
        if check.is_public:
            await self._broadcast(self._public, payload)

    async def broadcast_admin_changed(self) -> None:
        """Сигнал для админ-канала "что-то из состава/настроек изменилось,
        обновись" — используется CRUD-эндпоинтами (создание/удаление/пауза
        чека или группы, окна обслуживания), у которых нет естественного
        события уровня пробы. Без деталей полезной нагрузки: фронтенд просто
        перезапрашивает списки, это дешевле и надёжнее, чем воспроизводить
        каждую мутацию по кусочкам на клиенте."""
        await self._broadcast(self._admin, {"type": "admin.changed"})

    async def broadcast_incident_event(self, check: Check, event: IncidentEvent) -> None:
        payload = {
            "type": f"incident.{event.kind}",
            "check_id": check.id,
            "group_id": check.group_id,
            "incident_id": event.incident_id,
            "started_at": event.started_at.isoformat(),
            "ended_at": event.ended_at.isoformat() if event.ended_at else None,
        }
        await self._broadcast(self._admin, payload)
        if check.is_public:
            await self._broadcast(self._public, payload)

    async def _broadcast(self, connections: set[WebSocket], payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for websocket in connections:
            try:
                await websocket.send_json(payload)
            except Exception:  # noqa: BLE001 - мёртвое соединение не должно ронять рассылку остальным
                dead.append(websocket)
        for websocket in dead:
            connections.discard(websocket)
