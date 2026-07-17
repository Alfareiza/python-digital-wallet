"""
Unit tests for WalletService.

These tests must NOT use a real database or make real HTTP calls.
Use fakes/stubs for WalletRepository and PaymentGateway.
"""
import uuid
from decimal import Decimal

import pytest

from src.gateway.base import PaymentIntent
from src.wallet.models import Transaction, TransactionStatus, Wallet, WalletStatus
from src.wallet.schemas import DepositRequest
from src.wallet.service import WalletFrozenError, WalletNotFoundError, WalletService


# ---------------------------------------------------------------------------
# Fakes — implement these as part of your submission
# ---------------------------------------------------------------------------

class FakeWalletRepository:
    """In-memory replacement for WalletRepository.

    WalletService also calls `commit`/`refresh` directly on the session it is
    given, so this fake doubles as that session for the methods under test.
    """

    def __init__(self, wallet: Wallet | None = None):
        """Initialize the fake repository with an optional pre-loaded wallet."""
        self.wallet = wallet

    async def get_by_user_id(self, user_id: uuid.UUID) -> Wallet | None:
        """Return the wallet if it matches the given user_id, else None."""
        if self.wallet is not None and self.wallet.user_id == user_id:
            return self.wallet
        return None

    async def create_transaction(self, **kwargs) -> Transaction:
        """Create a new Transaction with the given fields."""
        return Transaction(id=uuid.uuid4(), **kwargs)

    async def commit(self) -> None:
        """No-op stub for session commit."""
        pass

    async def refresh(self, obj) -> None:
        """No-op stub for session refresh."""
        pass


class FakeGateway:
    """Stub PaymentGateway that returns predictable results without HTTP calls."""

    def __init__(self, reference: str = "pi_fake_123", should_fail: bool = False):
        """Initialize the gateway stub with an optional reference and failure mode."""
        self.reference = reference
        self.should_fail = should_fail

    async def create_deposit_intent(self, amount: Decimal, currency: str, metadata: dict) -> PaymentIntent:
        """Return a fake PaymentIntent or raise RuntimeError if configured to fail."""
        if self.should_fail:
            raise RuntimeError("gateway unavailable")
        return PaymentIntent(
            gateway_reference=self.reference, client_secret="secret_abc", status="requires_payment_method"
        )


# ---------------------------------------------------------------------------
# Deposit tests
# ---------------------------------------------------------------------------

class TestDeposit:
    async def test_creates_pending_transaction_with_gateway_reference(self):
        """Verify deposit creates a PENDING transaction with gateway_reference, leaving balance untouched."""
        # Arrange: active wallet, fake gateway returning a reference
        user_id = uuid.uuid4()
        wallet = Wallet(
            id=uuid.uuid4(), user_id=user_id, balance=Decimal("100.00"), currency="BRL", status=WalletStatus.ACTIVE
        )
        fake_repo = FakeWalletRepository(wallet)
        service = WalletService(session=fake_repo, gateway=FakeGateway(reference="pi_test_123"))
        service.repo = fake_repo

        # Act
        transaction = await service.deposit(user_id, DepositRequest(amount=Decimal("50.00")))

        # Assert: transaction status is PENDING, balance is unchanged, gateway_reference set
        assert transaction.status == TransactionStatus.PENDING
        assert transaction.gateway_reference == "pi_test_123"
        assert transaction.balance_before == Decimal("100.00")
        assert transaction.balance_after == Decimal("100.00")
        assert wallet.balance == Decimal("100.00")

    async def test_raises_when_wallet_frozen(self):
        """Verify deposit raises WalletFrozenError when wallet status is FROZEN."""
        user_id = uuid.uuid4()
        wallet = Wallet(
            id=uuid.uuid4(), user_id=user_id, balance=Decimal("10.00"), currency="BRL", status=WalletStatus.FROZEN
        )
        fake_repo = FakeWalletRepository(wallet)
        service = WalletService(session=fake_repo, gateway=FakeGateway())
        service.repo = fake_repo

        with pytest.raises(WalletFrozenError):
            await service.deposit(user_id, DepositRequest(amount=Decimal("10.00")))

    async def test_raises_when_wallet_not_found(self):
        """Verify deposit raises WalletNotFoundError when no wallet exists for the user."""
        fake_repo = FakeWalletRepository(wallet=None)
        service = WalletService(session=fake_repo, gateway=FakeGateway())
        service.repo = fake_repo

        with pytest.raises(WalletNotFoundError):
            await service.deposit(uuid.uuid4(), DepositRequest(amount=Decimal("10.00")))


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
