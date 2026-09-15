from fastapi import Request

from app.scheduler.engine import Scheduler


def get_scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler
