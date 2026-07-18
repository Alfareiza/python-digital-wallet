"""
Integration tests for wallet creation (GET/POST /wallet).

These tests hit a real PostgreSQL instance (managed by conftest.py).
"""
from decimal import Decimal

from httpx import AsyncClient


class TestWalletCreation:
    async def test_get_creates_wallet_on_first_access(self, client: AsyncClient, register_user):
        """Verify GET /wallet auto-creates a wallet (balance 0, ACTIVE) for a user with none, returning 201."""
        headers = await register_user("get.creates@example.com")

        resp = await client.get("/wallet", headers=headers)

        assert resp.status_code == 201
        body = resp.json()
        assert Decimal(body["balance"]) == Decimal("0.00")
        assert body["status"] == "ACTIVE"

    async def test_get_is_idempotent_after_creation(self, client: AsyncClient, register_user):
        """Verify a second GET /wallet returns the same wallet with 200, without creating another one."""
        headers = await register_user("get.idempotent@example.com")

        first = await client.get("/wallet", headers=headers)
        second = await client.get("/wallet", headers=headers)

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]

    async def test_post_creates_wallet_on_first_access(self, client: AsyncClient, register_user):
        """Verify POST /wallet creates a wallet (balance 0, ACTIVE) for a user with none, returning 201."""
        headers = await register_user("post.creates@example.com")

        resp = await client.post("/wallet", headers=headers)

        assert resp.status_code == 201
        body = resp.json()
        assert Decimal(body["balance"]) == Decimal("0.00")
        assert body["status"] == "ACTIVE"

    async def test_post_is_idempotent_for_an_existing_wallet(self, client: AsyncClient, register_user):
        """Verify a repeated POST /wallet returns the existing wallet with 200, without erroring."""
        headers = await register_user("post.idempotent@example.com")

        first = await client.post("/wallet", headers=headers)
        second = await client.post("/wallet", headers=headers)

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]

    async def test_requires_authentication(self, client: AsyncClient):
        """Verify POST /wallet rejects unauthenticated requests."""
        resp = await client.post("/wallet")
        assert resp.status_code == 401
