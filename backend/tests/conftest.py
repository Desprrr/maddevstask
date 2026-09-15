import asyncio

import asyncpg
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.alerting.dispatcher import AlertDispatcher
from app.alerting.email_sender import FakeEmailSender
from app.db import Base, get_db
from app.main import app, make_on_result
from app.realtime.connection_manager import ConnectionManager
from app.scheduler.engine import Scheduler
from app.scheduler.prober import close_shared_client

TEST_DATABASE_URL = "postgresql+asyncpg://monitor:monitor@localhost:5432/monitor_test"

# NullPool: с pytest-asyncio каждый тест может получить свой event loop, а пул
# asyncpg-соединений привязан к тому loop'у, где он создан. NullPool не держит
# соединения между запросами — каждое открывается/закрывается заново, поэтому
# кросс-loop переиспользование соединения невозможно в принципе.
test_engine = create_async_engine(TEST_DATABASE_URL, connect_args={"ssl": False}, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await test_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _quiet_expected_cancellation_noise():
    """С NullPool каждая операция открывает новое asyncpg-соединение; когда
    тест разом отменяет много задач планировщика (test_scheduler_scale.py —
    50 штук), часть из них попадает в отмену прямо во время установки
    соединения. Сам asyncpg в этом случае иногда не успевает подхватить своё
    же исключение назад в отменённую задачу — оно всплывает отдельным
    "Future exception was never retrieved" в обработчике исключений event
    loop'а. Тесты при этом проходят корректно (это не влияет на результат
    ни одного assert) — просто убираем шум из вывода, а не прячем реальную
    ошибку: любое другое исключение по-прежнему идёт в дефолтный handler."""
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def handler(loop, context):
        if isinstance(context.get("exception"), asyncpg.exceptions.ConnectionDoesNotExistError):
            return
        if previous_handler is not None:
            previous_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables():
    yield
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture
async def client():
    # Не запускаем настоящий app-lifespan (он поднял бы планировщик на проде,
    # ASGITransport и не вызывает lifespan сам по себе) — вместо этого явно
    # ставим планировщик, привязанный к тестовой БД, в app.state.
    connection_manager = ConnectionManager()
    app.state.connection_manager = connection_manager

    scheduler = Scheduler(TestSessionLocal, on_result=make_on_result(connection_manager, TestSessionLocal))
    app.state.scheduler = scheduler
    await scheduler.start()

    dispatcher = AlertDispatcher(TestSessionLocal, FakeEmailSender(TestSessionLocal))
    app.state.alert_dispatcher = dispatcher
    dispatcher.start()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await dispatcher.shutdown()
        await scheduler.shutdown()
        # prober._client — общий httpx.AsyncClient на весь процесс, а у
        # pytest-asyncio каждый тест может получить свой event loop; не
        # сбросить — поймать тот же межloop'овый краш, что и с БД-пулом.
        await close_shared_client()
