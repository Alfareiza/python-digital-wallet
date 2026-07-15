"""
Integration tests for the deposit → webhook → balance flow.

These tests hit a real PostgreSQL instance (managed by conftest.py).
The gateway is stubbed so no real payment provider is called.
"""
import pytest
from httpx import AsyncClient


class TestDepositWebhookFlow:
    async def test_webhook_credits_balance_on_payment_success(self, client: AsyncClient):
        # 1. Register a user and obtain a JWT
        # 2. POST /wallet/deposit — capture the gateway_reference from the response
        # 3. POST /webhooks/gateway with a validly-signed success event
        # 4. GET /wallet — assert balance increased by the deposited amount
        # 5. GET /transactions — assert the transaction is COMPLETED
        pytest.skip("not implemented")

    async def test_webhook_is_idempotent(self, client: AsyncClient):
        # POST the same webhook event twice
        # Assert the balance was only credited once
        pytest.skip("not implemented")

    async def test_duplicate_gateway_reference_is_rejected(self, client: AsyncClient):
        # The gateway_reference column has a UNIQUE constraint
        # Sending two deposits that resolve to the same gateway_reference must fail safely
        pytest.skip("not implemented")

    async def test_webhook_rejects_invalid_signature(self, client: AsyncClient):
        # POST /webhooks/gateway with a tampered or missing signature
        # Assert HTTP 400
        pytest.skip("not implemented")
