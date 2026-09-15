from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    # Дефолтные pool_size=5/max_overflow=10 маловаты под требование "50
    # проверок с интервалом 30с не мешают друг другу": планировщик — по
    # одной короткой транзакции на пробу на чек, при большом количестве
    # чеков конкурентных подключений к БД нужно с запасом.
    pool_size=20,
    max_overflow=20,
    connect_args={"ssl": settings.database_ssl},
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
