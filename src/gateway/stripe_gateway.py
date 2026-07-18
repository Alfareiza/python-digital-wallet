import hashlib
import hmac
import json
import logging
from decimal import Decimal

import httpx

from src.gateway.base import PaymentIntent

logger = logging.getLogger(__name__)

STRIPE_API_BASE = "https://api.stripe.com/v1"


def _to_minor_units(amount: Decimal) -> int:
    """Convert a decimal amount to its smallest currency unit (cents), assuming a 2-decimal currency."""
    return int((amount * 100).to_integral_value())


class StripeGateway:
    """PaymentGateway implementation backed by direct REST calls to the Stripe API."""

    def __init__(self, secret_key: str, webhook_secret: str = "", *, simulate_payouts: bool = True):
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self._simulate_payouts = simulate_payouts

    async def create_deposit_intent(self, amount: Decimal, currency: str, metadata: dict) -> PaymentIntent:
        """Create a Stripe PaymentIntent so the user can fund a deposit via card."""
        payload = {
            "amount": str(_to_minor_units(amount)),
            "currency": currency.lower(),
            "automatic_payment_methods[enabled]": "true",  # This tells Stripe: "Let the user pick ANY payment method you support."
        }
        for key, value in metadata.items():
            payload[f"metadata[{key}]"] = str(value)

        data = await self._post("/payment_intents", payload, idempotency_key=metadata.get("transaction_id"))
        return PaymentIntent(gateway_reference=data["id"], client_secret=data.get("client_secret"), status=data["status"])

    async def create_payout(self, amount: Decimal, destination: dict, metadata: dict) -> PaymentIntent:
        """Create a payout for a withdrawal.

        In simulate mode (default for local dev), returns a fake reference so the
        withdraw flow can be completed via POST /confirm-payout/{gateway_reference}.
        Real Stripe Payouts only pay out to the platform's own bank account; per-user
        PIX/bank routing would require Stripe Connect — `destination` is stored for
        traceability.
        """
        transaction_id = metadata.get("transaction_id", "unknown")
        if self._simulate_payouts:
            return PaymentIntent(
                gateway_reference=f"po_sim_{transaction_id}",
                client_secret=None,
                status="pending",
            )

        payload = {
            "amount": str(_to_minor_units(amount)),
            "currency": metadata.get("currency", "BRL").lower(),
            "metadata[destination]": json.dumps(destination),
        }
        for key, value in metadata.items():
            payload[f"metadata[{key}]"] = str(value)

        data = await self._post("/payouts", payload, idempotency_key=transaction_id)
        return PaymentIntent(gateway_reference=data["id"], client_secret=None, status=data["status"])

    def verify_webhook(self, payload: bytes, signature: str) -> dict:
        """Verify a Stripe webhook signature (per Stripe's signing scheme) and return the parsed event."""
        parts = dict(item.split("=", 1) for item in signature.split(","))
        timestamp, expected_signature = parts.get("t"), parts.get("v1")
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        computed_signature = hmac.new(
            self._webhook_secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not expected_signature or not hmac.compare_digest(computed_signature, expected_signature):
            raise ValueError("Invalid Stripe webhook signature")
        return json.loads(payload)

    async def _post(self, path: str, payload: dict, idempotency_key: str | None) -> dict:
        """Send an authenticated, idempotency-keyed POST request to the Stripe REST API."""
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        async with httpx.AsyncClient(auth=(self._secret_key, "")) as client:
            response = await client.post(f"{STRIPE_API_BASE}{path}", data=payload, headers=headers)
        if response.is_error:
            logger.error(f"Stripe API error on {path}: {response.text}")
       
        response.raise_for_status()
        return response.json()
