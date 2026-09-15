from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.alerting.dispatcher import AlertDispatcher
from app.alerting.email_sender import make_email_sender
from app.api import checks, groups, maintenance_windows
from app.config import get_settings
from app.db import async_session_factory
from app.incidents import make_incident_evaluator
from app.scheduler.engine import Scheduler

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    scheduler = Scheduler(async_session_factory, on_result=make_incident_evaluator(async_session_factory))
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
