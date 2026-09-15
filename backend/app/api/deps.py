from fastapi import Request

from app.realtime.connection_manager import ConnectionManager
from app.scheduler.engine import Scheduler


def get_scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler


def get_connection_manager(request: Request) -> ConnectionManager:
    return request.app.state.connection_manager
