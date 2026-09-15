from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.alerting.dispatcher import AlertDispatcher
from app.alerting.email_sender import make_email_sender
from app.api import checks, groups, maintenance_windows, ws
from app.config import get_settings
from app.db import async_session_factory
from app.incidents import make_incident_evaluator
from app.models.check import Check
from app.models.check_result import CheckResult
from app.realtime.connection_manager import ConnectionManager
from app.scheduler.engine import Scheduler

settings = get_settings()


def make_on_result(
    connection_manager: ConnectionManager,
    session_factory: async_sessionmaker = async_session_factory,
):
    evaluate_incident = make_incident_evaluator(session_factory)

    async def on_result(check: Check, result: CheckResult) -> None:
        await connection_manager.broadcast_check_result(check, result)
        event = await evaluate_incident(check, result)
        if event is not None:
            await connection_manager.broadcast_incident_event(check, event)

    return on_result


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    connection_manager = ConnectionManager()
    app.state.connection_manager = connection_manager

    scheduler = Scheduler(async_session_factory, on_result=make_on_result(connection_manager))
    app.state.scheduler = scheduler
    await scheduler.start()

    email_sender = make_email_sender(settings, async_session_factory)
    dispatcher = AlertDispatcher(async_session_factory, email_sender)
    app.state.alert_dispatcher = dispatcher
    dispatcher.start()

    try:
        yield
    finally:
        await dispatcher.shutdown()
        await scheduler.shutdown()


app = FastAPI(title="Site Availability Monitor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(groups.router, prefix="/api")
app.include_router(checks.router, prefix="/api")
app.include_router(maintenance_windows.router, prefix="/api")
app.include_router(ws.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
