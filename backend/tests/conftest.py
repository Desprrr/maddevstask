import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import Base, get_db
from app.main import app
from app.scheduler.engine import Scheduler

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
    scheduler = Scheduler(TestSessionLocal)
    app.state.scheduler = scheduler
    await scheduler.start()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await scheduler.shutdown()
