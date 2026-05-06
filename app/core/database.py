from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None


async def init_db() -> None:
    global _engine, _session_factory
    url = settings.DATABASE_URL
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_async_engine(url, echo=False, connect_args=connect_args)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


async def get_db() -> AsyncSession:
    async with _session_factory() as session:
        yield session
