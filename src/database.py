import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def create_all_tables(target_engine: AsyncEngine | None = None) -> None:
    """Create all ORM-declared tables on `target_engine` (default: the app engine) if missing.

    Idempotent — safe to call on every startup. Imports every model module first so
    they're registered on `Base.metadata` regardless of router import order.
    """
    from src.auth import models as _auth_models  # noqa: F401
    from src.wallet import models as _wallet_models  # noqa: F401

    async with (target_engine or engine).begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def init_db(retries: int = 5, delay_seconds: float = 2.0) -> None:
    """Create tables on the app's configured database at startup.

    Retries briefly to tolerate the window where Postgres reports healthy
    (pg_isready) but isn't yet accepting connections.
    """
    for attempt in range(1, retries + 1):
        try:
            await create_all_tables()
            return
        except OperationalError:
            if attempt == retries:
                raise
            logger.warning(f"Database not ready (attempt {attempt}/{retries}); retrying...")
       
            await asyncio.sleep(delay_seconds)
