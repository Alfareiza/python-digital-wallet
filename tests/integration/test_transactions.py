"""
Integration tests for GET /transactions — query-param filtering, pagination, and scoping.

These tests hit a real PostgreSQL instance (managed by conftest.py).
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.wallet.models import TransactionStatus, TransactionType, Wallet


@pytest_asyncio.fixture
async def wallet_headers(client: AsyncClient, register_user, db_session: AsyncSession) -> tuple[User, Wallet]:
    """Register a user, create their wallet via the API, and return (user, wallet)."""
    user = await register_user("transactions@example.com")
    resp = await client.post("/wallet", headers=user.headers)
    wallet = await db_session.get(Wallet, uuid.UUID(resp.json()["id"]))
    return user, wallet


class TestListTransactionsFilters:
    async def test_filters_by_start_and_end_date(self, client: AsyncClient, wallet_headers, make_transaction):
        """Verify start_date/end_date (DD/MM/YYYY) narrow results to transactions created within that window."""
        user, wallet = wallet_headers
        now = datetime.now(timezone.utc)
        too_old = await make_transaction(wallet_id=wallet.id, created_at=now - timedelta(days=10))
        in_range = await make_transaction(wallet_id=wallet.id, created_at=now - timedelta(days=5))
        too_new = await make_transaction(wallet_id=wallet.id, created_at=now + timedelta(days=10))

        resp = await client.get(
            "/transactions",
            params={
                "start_date": (now - timedelta(days=7)).strftime("%d/%m/%Y"),
                "end_date": now.strftime("%d/%m/%Y"),
            },
            headers=user.headers,
        )

        assert resp.status_code == 200
        returned_ids = {item["id"] for item in resp.json()["items"]}
        assert returned_ids == {str(in_range.id)}
        assert str(too_old.id) not in returned_ids
        assert str(too_new.id) not in returned_ids

    async def test_end_date_is_inclusive_of_the_whole_day(self, client: AsyncClient, wallet_headers, make_transaction):
        """Verify end_date=today still includes a transaction created later that same day."""
        user, wallet = wallet_headers
        now = datetime.now(timezone.utc)
        later_today = await make_transaction(wallet_id=wallet.id, created_at=now.replace(hour=23, minute=0))

        resp = await client.get("/transactions", params={"end_date": now.strftime("%d/%m/%Y")}, headers=user.headers)

        assert resp.status_code == 200
        returned_ids = {item["id"] for item in resp.json()["items"]}
        assert str(later_today.id) in returned_ids

    async def test_rejects_invalid_date_format(self, client: AsyncClient, wallet_headers):
        """Verify a start_date not in DD/MM/YYYY format (e.g. ISO 8601) is rejected with 422."""
        user, _wallet = wallet_headers

        resp = await client.get(
            "/transactions", params={"start_date": "2026-07-17"}, headers=user.headers
        )

        assert resp.status_code == 422

    async def test_filters_by_min_and_max_amount(self, client: AsyncClient, wallet_headers, make_transaction):
        """Verify min_amount/max_amount only return transactions within that inclusive range."""
        user, wallet = wallet_headers
        below = await make_transaction(wallet_id=wallet.id, amount=Decimal("5.00"))
        in_range = await make_transaction(wallet_id=wallet.id, amount=Decimal("15.00"))
        above = await make_transaction(wallet_id=wallet.id, amount=Decimal("35.00"))

        resp = await client.get(
            "/transactions", params={"min_amount": "10.00", "max_amount": "30.00"}, headers=user.headers
        )

        assert resp.status_code == 200
        returned_ids = {item["id"] for item in resp.json()["items"]}
        assert returned_ids == {str(in_range.id)}
        assert str(below.id) not in returned_ids
        assert str(above.id) not in returned_ids

    async def test_filters_by_type(self, client: AsyncClient, wallet_headers, make_transaction):
        """Verify the `type` query param only returns transactions of that TransactionType."""
        user, wallet = wallet_headers
        deposit = await make_transaction(wallet_id=wallet.id, type=TransactionType.DEPOSIT)
        withdrawal = await make_transaction(wallet_id=wallet.id, type=TransactionType.WITHDRAWAL)

        resp = await client.get("/transactions", params={"type": "WITHDRAWAL"}, headers=user.headers)

        assert resp.status_code == 200
        returned_ids = {item["id"] for item in resp.json()["items"]}
        assert returned_ids == {str(withdrawal.id)}
        assert str(deposit.id) not in returned_ids

    async def test_filters_by_status(self, client: AsyncClient, wallet_headers, make_transaction):
        """Verify the `status` query param only returns transactions in that TransactionStatus."""
        user, wallet = wallet_headers
        pending = await make_transaction(wallet_id=wallet.id, status=TransactionStatus.PENDING)
        failed = await make_transaction(wallet_id=wallet.id, status=TransactionStatus.FAILED)

        resp = await client.get("/transactions", params={"status": "PENDING"}, headers=user.headers)

        assert resp.status_code == 200
        returned_ids = {item["id"] for item in resp.json()["items"]}
        assert returned_ids == {str(pending.id)}
        assert str(failed.id) not in returned_ids

    async def test_combines_multiple_filters(self, client: AsyncClient, wallet_headers, make_transaction):
        """Verify type, status, and min_amount can all be applied together in a single request."""
        user, wallet = wallet_headers
        match = await make_transaction(
            wallet_id=wallet.id, type=TransactionType.WITHDRAWAL, status=TransactionStatus.COMPLETED,
            amount=Decimal("50.00"),
        )
        wrong_type = await make_transaction(
            wallet_id=wallet.id, type=TransactionType.DEPOSIT, status=TransactionStatus.COMPLETED,
            amount=Decimal("50.00"),
        )
        wrong_amount = await make_transaction(
            wallet_id=wallet.id, type=TransactionType.WITHDRAWAL, status=TransactionStatus.COMPLETED,
            amount=Decimal("5.00"),
        )

        resp = await client.get(
            "/transactions",
            params={"type": "WITHDRAWAL", "status": "COMPLETED", "min_amount": "10.00"},
            headers=user.headers,
        )

        assert resp.status_code == 200
        returned_ids = {item["id"] for item in resp.json()["items"]}
        assert returned_ids == {str(match.id)}
        assert str(wrong_type.id) not in returned_ids
        assert str(wrong_amount.id) not in returned_ids

    async def test_paginates_with_page_and_page_size(self, client: AsyncClient, wallet_headers, make_transaction):
        """Verify page/page_size slice the (newest-first) results and `total` reflects the full count."""
        user, wallet = wallet_headers
        now = datetime.now(timezone.utc)
        for i, amount in enumerate(["10.00", "20.00", "30.00", "40.00", "50.00"]):
            await make_transaction(wallet_id=wallet.id, amount=Decimal(amount), created_at=now + timedelta(minutes=i))

        resp = await client.get("/transactions", params={"page": 2, "page_size": 2}, headers=user.headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        assert body["page"] == 2
        assert body["page_size"] == 2
        assert [item["amount"] for item in body["items"]] == ["30.00", "20.00"]

    async def test_only_returns_transactions_for_the_authenticated_users_wallet(
        self, client: AsyncClient, wallet_headers, make_transaction, register_user, db_session: AsyncSession
    ):
        """Verify another user's transactions are never included in the caller's results."""
        user, wallet = wallet_headers
        own_transaction = await make_transaction(wallet_id=wallet.id)

        other_user = await register_user("other.transactions@example.com")
        other_wallet_resp = await client.post("/wallet", headers=other_user.headers)
        other_wallet_id = uuid.UUID(other_wallet_resp.json()["id"])
        await make_transaction(wallet_id=other_wallet_id)

        resp = await client.get("/transactions", headers=user.headers)

        assert resp.status_code == 200
        returned_ids = {item["id"] for item in resp.json()["items"]}
        assert returned_ids == {str(own_transaction.id)}

    async def test_requires_authentication(self, client: AsyncClient):
        """Verify GET /transactions rejects unauthenticated requests."""
        resp = await client.get("/transactions")
        assert resp.status_code == 401
