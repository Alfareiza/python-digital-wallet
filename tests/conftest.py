import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings
from src.database import Base, create_all_tables, get_session
from src.main import app
from src.wallet.models import Wallet, WalletStatus

# Tests only run inside the `api` container (`docker compose exec api pytest`), against a
# disposable database on the same `db` service — see `settings.test_database_url`.
TEST_DATABASE_URL = settings.test_database_url
_test_db_name = make_url(TEST_DATABASE_URL).database
_maintenance_url = make_url(TEST_DATABASE_URL).set(database="postgres")

_engine = create_async_engine(TEST_DATABASE_URL)
_TestSession = async_sessionmaker(_engine, expire_on_commit=False)


@pytest.fixture
def make_wallet():
    """Return a factory that builds in-memory Wallet instances with sensible defaults."""

    def _make_wallet(*, user_id: uuid.UUID, **kwargs) -> Wallet:
        """Build a Wallet, applying defaults unless overridden via keyword arguments."""
        return Wallet(
            id=kwargs.pop("id", uuid.uuid4()),
            user_id=user_id,
            currency=kwargs.pop("currency", "BRL"),
            balance=kwargs.pop("balance", Decimal("0.00")),
            status=kwargs.pop("status", WalletStatus.ACTIVE),
            **kwargs,
        )

    return _make_wallet


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _temporary_database():
    """Drop and recreate the disposable test database once per test session."""
    maintenance_engine = create_async_engine(_maintenance_url, isolation_level="AUTOCOMMIT")
    async with maintenance_engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{_test_db_name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{_test_db_name}"'))
    await maintenance_engine.dispose()
    yield
    await _engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def reset_db():
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await create_all_tables(_engine)
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
