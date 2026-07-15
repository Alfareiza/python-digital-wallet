"""
Unit tests for WalletService.

These tests must NOT use a real database or make real HTTP calls.
Use fakes/stubs for WalletRepository and PaymentGateway.
"""
import uuid
from decimal import Decimal

import pytest


# ---------------------------------------------------------------------------
# Fakes — implement these as part of your submission
# ---------------------------------------------------------------------------

class FakeWalletRepository:
    """In-memory replacement for WalletRepository."""
    pass


class FakeGateway:
    """Stub PaymentGateway that returns predictable results without HTTP calls."""
    pass


# ---------------------------------------------------------------------------
# Deposit tests
# ---------------------------------------------------------------------------

class TestDeposit:
    async def test_creates_pending_transaction_with_gateway_reference(self):
        # Arrange: active wallet, fake gateway returning a reference
        # Act: service.deposit(...)
        # Assert: transaction status is PENDING, balance is unchanged, gateway_reference set
        pytest.skip("not implemented")

    async def test_raises_when_wallet_frozen(self):
        pytest.skip("not implemented")

    async def test_raises_when_wallet_not_found(self):
        pytest.skip("not implemented")


# ---------------------------------------------------------------------------
# Withdrawal tests
# ---------------------------------------------------------------------------

class TestWithdraw:
    async def test_debits_balance_before_gateway_call(self):
        # Assert balance is reduced in the DB before the payout is initiated
        pytest.skip("not implemented")

    async def test_raises_on_insufficient_funds(self):
        pytest.skip("not implemented")

    async def test_releases_reservation_on_gateway_failure(self):
        # Simulate gateway raising an exception
        # Assert balance is restored and transaction is marked FAILED
        pytest.skip("not implemented")


# ---------------------------------------------------------------------------
# Transfer tests
# ---------------------------------------------------------------------------

class TestTransfer:
    async def test_debit_and_credit_are_linked(self):
        # Assert counterpart_transaction_id is set on both sides
        pytest.skip("not implemented")

    async def test_total_supply_is_conserved(self):
        # Assert sender_balance_after + receiver_balance_after == sender_balance_before + receiver_balance_before
        pytest.skip("not implemented")

    async def test_raises_on_insufficient_funds(self):
        pytest.skip("not implemented")

    async def test_raises_when_recipient_not_found(self):
        pytest.skip("not implemented")
