import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database import Base, get_session
from src.main import app

# Requires a running PostgreSQL instance. Start one with:
#   docker run -e POSTGRES_USER=wallet -e POSTGRES_PASSWORD=wallet \
#              -e POSTGRES_DB=wallet_test -p 5433:5432 postgres:15
TEST_DATABASE_URL = "postgresql+asyncpg://wallet:wallet@localhost:5433/wallet_test"

_engine = create_async_engine(TEST_DATABASE_URL)
_TestSession = async_sessionmaker(_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with _TestSession() as s:
        yield s


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncClient:
    async def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
