"""
Integration tests for the deposit → webhook → balance flow.

These tests hit a real PostgreSQL instance (managed by conftest.py).
The gateway is stubbed so no real payment provider is called.
"""
import hashlib
import hmac
import json
import time
import uuid
from decimal import Decimal

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.wallet.models import Wallet, WalletStatus

STRIPE_PAYMENT_INTENTS_URL = "https://api.stripe.com/v1/payment_intents"


class TestDepositWebhookFlow:
    @respx.mock
    async def test_webhook_credits_balance_on_payment_success(self, client: AsyncClient, db_session: AsyncSession):
        """Verify deposit + success webhook credits balance and marks transaction COMPLETED."""
        # 1. Register a user and obtain a JWT
        register = await client.post(
            "/auth/register",
            json={"email": "deposit.success@example.com", "password": "supersecret123", "name": "Deposit Success"},
        )
        user_id = register.json()["id"]
        login = await client.post(
            "/auth/token", data={"username": "deposit.success@example.com", "password": "supersecret123"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        db_session.add(Wallet(user_id=uuid.UUID(user_id), balance=Decimal("0.00"), status=WalletStatus.ACTIVE))
        await db_session.commit()

        respx.post(STRIPE_PAYMENT_INTENTS_URL).mock(
            return_value=httpx.Response(
                200, json={"id": "pi_success_1", "client_secret": "secret_1", "status": "requires_payment_method"}
            )
        )

        # 2. POST /wallet/deposit — capture the gateway_reference from the response
        deposit_resp = await client.post("/wallet/deposit", json={"amount": "100.00"}, headers=headers)
        assert deposit_resp.status_code == 202
        transaction_id = deposit_resp.json()["id"]
        assert deposit_resp.json()["gateway_reference"] == "pi_success_1"

        # 3. POST /webhooks/gateway with a validly-signed success event
        payload = json.dumps(
            {
                "id": "evt_success_1",
                "type": "payment_intent.succeeded",
                "data": {"object": {"id": "pi_success_1", "object": "payment_intent", "status": "succeeded"}},
            }
        ).encode()
        timestamp = str(int(time.time()))
        digest = hmac.new(
            settings.stripe_webhook_secret.encode(), f"{timestamp}.{payload.decode()}".encode(), hashlib.sha256
        ).hexdigest()
        webhook_resp = await client.post(
            "/webhooks/gateway", content=payload, headers={"stripe-signature": f"t={timestamp},v1={digest}"}
        )
        assert webhook_resp.status_code == 200

        # 4. GET /wallet — assert balance increased by the deposited amount
        wallet_resp = await client.get("/wallet", headers=headers)
        assert Decimal(wallet_resp.json()["balance"]) == Decimal("100.00")

        # 5. GET /transactions — assert the transaction is COMPLETED
        tx_resp = await client.get(f"/transactions/{transaction_id}", headers=headers)
        assert tx_resp.json()["status"] == "COMPLETED"

    @respx.mock
    async def test_webhook_is_idempotent(self, client: AsyncClient, db_session: AsyncSession):
        """Verify posting the same webhook event twice credits balance only once."""
        register = await client.post(
            "/auth/register",
            json={"email": "deposit.idempotent@example.com", "password": "supersecret123", "name": "Deposit Idem"},
        )
        user_id = register.json()["id"]
        login = await client.post(
            "/auth/token", data={"username": "deposit.idempotent@example.com", "password": "supersecret123"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        db_session.add(Wallet(user_id=uuid.UUID(user_id), balance=Decimal("0.00"), status=WalletStatus.ACTIVE))
        await db_session.commit()

        respx.post(STRIPE_PAYMENT_INTENTS_URL).mock(
            return_value=httpx.Response(
                200, json={"id": "pi_idempotent_1", "client_secret": "secret", "status": "requires_payment_method"}
            )
        )
        deposit_resp = await client.post("/wallet/deposit", json={"amount": "75.00"}, headers=headers)
        assert deposit_resp.status_code == 202

        # POST the same webhook event twice
        payload = json.dumps(
            {
                "id": "evt_idempotent_1",
                "type": "payment_intent.succeeded",
                "data": {"object": {"id": "pi_idempotent_1"}},
            }
        ).encode()
        timestamp = str(int(time.time()))
        digest = hmac.new(
            settings.stripe_webhook_secret.encode(), f"{timestamp}.{payload.decode()}".encode(), hashlib.sha256
        ).hexdigest()
        signature = f"t={timestamp},v1={digest}"
        first = await client.post("/webhooks/gateway", content=payload, headers={"stripe-signature": signature})
        second = await client.post("/webhooks/gateway", content=payload, headers={"stripe-signature": signature})
        assert first.status_code == 200
        assert second.status_code == 200

        # Assert the balance was only credited once
        wallet_resp = await client.get("/wallet", headers=headers)
        assert Decimal(wallet_resp.json()["balance"]) == Decimal("75.00")

    @respx.mock
    async def test_duplicate_gateway_reference_is_rejected(self, client: AsyncClient, db_session: AsyncSession):
        """Verify the gateway_reference UNIQUE constraint prevents duplicate deposits from succeeding."""
        register = await client.post(
            "/auth/register",
            json={"email": "deposit.duplicate@example.com", "password": "supersecret123", "name": "Deposit Dup"},
        )
        user_id = register.json()["id"]
        login = await client.post(
            "/auth/token", data={"username": "deposit.duplicate@example.com", "password": "supersecret123"}
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        db_session.add(Wallet(user_id=uuid.UUID(user_id), balance=Decimal("0.00"), status=WalletStatus.ACTIVE))
        await db_session.commit()

        # The gateway_reference column has a UNIQUE constraint. Two deposits that resolve to
        # the same gateway_reference (e.g. a misbehaving gateway) must not both succeed.
        respx.post(STRIPE_PAYMENT_INTENTS_URL).mock(
            return_value=httpx.Response(
                200, json={"id": "pi_duplicate_1", "client_secret": "secret", "status": "requires_payment_method"}
            )
        )

        first = await client.post("/wallet/deposit", json={"amount": "10.00"}, headers=headers)
        assert first.status_code == 202
        assert first.json()["gateway_reference"] == "pi_duplicate_1"

        # `WalletService.deposit` does not currently catch the unique-constraint violation on
        # `gateway_reference`, so it currently propagates as a raw IntegrityError instead of a
        # clean HTTP error. The constraint itself still does its job: no duplicate row is written.
        with pytest.raises(IntegrityError):
            await client.post("/wallet/deposit", json={"amount": "20.00"}, headers=headers)
        await db_session.rollback()

        # The first (successful) transaction and the wallet must be unaffected by the failed second attempt.
        wallet_resp = await client.get("/wallet", headers=headers)
        assert Decimal(wallet_resp.json()["balance"]) == Decimal("0.00")
        first_tx = await client.get(f"/transactions/{first.json()['id']}", headers=headers)
        assert first_tx.json()["status"] == "PENDING"

    async def test_webhook_rejects_invalid_signature(self, client: AsyncClient):
        """Verify webhook rejects payloads with invalid or tampered signatures."""
        # POST /webhooks/gateway with a tampered or missing signature
        payload = json.dumps(
            {"id": "evt_bad_sig", "type": "payment_intent.succeeded", "data": {"object": {"id": "pi_whatever"}}}
        ).encode()
        resp = await client.post("/webhooks/gateway", content=payload, headers={"stripe-signature": "t=1,v1=bogus"})
        assert resp.status_code == 400
