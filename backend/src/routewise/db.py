from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from routewise.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    pool_options: dict[str, object] = {}
    if settings.database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    else:
        pool_options = {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_timeout": settings.database_pool_timeout_seconds,
            "pool_recycle": settings.database_pool_recycle_seconds,
        }
    return create_async_engine(
        settings.database_url,
        echo=settings.sql_echo,
        pool_pre_ping=True,
        connect_args=connect_args,
        **pool_options,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_from_app(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
