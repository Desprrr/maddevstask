from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.realtime.connection_manager import ConnectionManager

router = APIRouter(tags=["realtime"])


def _manager(websocket: WebSocket) -> ConnectionManager:
    return websocket.app.state.connection_manager


@router.websocket("/ws/admin")
async def admin_ws(websocket: WebSocket) -> None:
    manager = _manager(websocket)
    await manager.connect_admin(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_admin(websocket)


@router.websocket("/ws/public")
async def public_ws(websocket: WebSocket) -> None:
    manager = _manager(websocket)
    await manager.connect_public(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_public(websocket)
