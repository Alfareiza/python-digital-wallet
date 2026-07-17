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
from src.wallet.schemas import DepositRequest, PixDestination, TransferRequest, WithdrawRequest
from src.wallet.service import (
    InsufficientFundsError,
    WalletFrozenError,
    WalletNotFoundError,
    WalletService,
)


# ---------------------------------------------------------------------------
# Fakes — implement these as part of your submission
# ---------------------------------------------------------------------------

class FakeWalletRepository:
    """In-memory replacement for WalletRepository.

    WalletService also calls `commit`/`refresh` directly on the session it is
    given, so this fake doubles as that session for the methods under test.
    """

    def __init__(self, wallet: Wallet | None = None, recipient_wallet: Wallet | None = None):
        """Initialize the fake repository with an optional pre-loaded wallet and transfer recipient."""
        self.wallet = wallet
        self.recipient_wallet = recipient_wallet

    async def get_by_user_id(self, user_id: uuid.UUID) -> Wallet | None:
        """Return the wallet if it matches the given user_id, else None."""
        if self.wallet is not None and self.wallet.user_id == user_id:
            return self.wallet
        return None

    async def get_for_update(self, wallet_id: uuid.UUID) -> Wallet | None:
        """Return whichever in-memory wallet matches wallet_id (no real row locking)."""
        for wallet in (self.wallet, self.recipient_wallet):
            if wallet is not None and wallet.id == wallet_id:
                return wallet
        return None

    async def create(self, user_id: uuid.UUID) -> Wallet:
        """Create and store a new wallet for user_id, mirroring the model defaults."""
        self.wallet = Wallet(id=uuid.uuid4(), user_id=user_id, balance=Decimal("0"), status=WalletStatus.ACTIVE)
        return self.wallet

    async def create_transaction(self, **kwargs) -> Transaction:
        """Create a new Transaction with the given fields."""
        return Transaction(id=uuid.uuid4(), **kwargs)

    async def commit(self) -> None:
        """No-op stub for session commit."""
        pass

    async def refresh(self, obj) -> None:
        """No-op stub for session refresh."""
        pass

    async def execute(self, query):
        """Stand in for the session-level recipient-by-email lookup used by WalletService.transfer."""
        return self

    def scalar_one_or_none(self) -> Wallet | None:
        """Mimic a SQLAlchemy Result, returning the configured recipient wallet."""
        return self.recipient_wallet


class FakeGateway:
    """Stub PaymentGateway that returns predictable results without HTTP calls."""

    def __init__(self, reference: str = "pi_fake_123", should_fail: bool = False, wallet: Wallet | None = None):
        """Initialize the gateway stub with an optional reference, failure mode, and wallet to observe."""
        self.reference = reference
        self.should_fail = should_fail
        self.wallet = wallet
        self.balance_at_payout_call: Decimal | None = None

    async def create_deposit_intent(self, amount: Decimal, currency: str, metadata: dict) -> PaymentIntent:
        """Return a fake PaymentIntent or raise RuntimeError if configured to fail."""
        if self.should_fail:
            raise RuntimeError("gateway unavailable")
        return PaymentIntent(
            gateway_reference=self.reference, client_secret="secret_abc", status="requires_payment_method"
        )

    async def create_payout(self, amount: Decimal, destination: dict, metadata: dict) -> PaymentIntent:
        """Record the observed wallet's balance at call time, then return a fake payout or raise if failing."""
        if self.wallet is not None:
            self.balance_at_payout_call = self.wallet.balance
        if self.should_fail:
            raise RuntimeError("gateway unavailable")
        return PaymentIntent(gateway_reference=self.reference, client_secret=None, status="paid")


# ---------------------------------------------------------------------------
# get_or_create_wallet tests
# ---------------------------------------------------------------------------

class TestGetOrCreateWallet:
    async def test_creates_wallet_with_zero_balance_and_active_status_when_none_exists(self):
        """Verify a missing wallet is created with balance 0 and status ACTIVE, and created=True."""
        user_id = uuid.uuid4()
        fake_repo = FakeWalletRepository(wallet=None)
        service = WalletService(session=fake_repo, gateway=FakeGateway())
        service.repo = fake_repo

        wallet, created = await service.get_or_create_wallet(user_id)

        assert created is True
        assert wallet.user_id == user_id
        assert wallet.balance == Decimal("0")
        assert wallet.status == WalletStatus.ACTIVE

    async def test_returns_existing_wallet_without_creating_a_new_one(self, make_wallet):
        """Verify an existing wallet is returned as-is, with created=False."""
        user_id = uuid.uuid4()
        wallet = make_wallet(user_id=user_id, balance=Decimal("42.00"))
        fake_repo = FakeWalletRepository(wallet)
        service = WalletService(session=fake_repo, gateway=FakeGateway())
        service.repo = fake_repo

        returned_wallet, created = await service.get_or_create_wallet(user_id)

        assert created is False
        assert returned_wallet is wallet
        assert returned_wallet.balance == Decimal("42.00")


# ---------------------------------------------------------------------------
# Deposit tests
# ---------------------------------------------------------------------------

class TestDeposit:
    async def test_creates_pending_transaction_with_gateway_reference(self, make_wallet):
        """Verify deposit creates a PENDING transaction with gateway_reference, leaving balance untouched."""
        # Arrange: active wallet, fake gateway returning a reference
        user_id = uuid.uuid4()
        wallet = make_wallet(user_id=user_id, balance=Decimal("100.00"))
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

    async def test_raises_when_wallet_frozen(self, make_wallet):
        """Verify deposit raises WalletFrozenError when wallet status is FROZEN."""
        user_id = uuid.uuid4()
        wallet = make_wallet(user_id=user_id, balance=Decimal("10.00"), status=WalletStatus.FROZEN)
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
    async def test_debits_balance_before_gateway_call(self, make_wallet):
        """Verify the wallet balance is already reduced by the time the payout gateway call happens."""
        user_id = uuid.uuid4()
        wallet = make_wallet(user_id=user_id, balance=Decimal("100.00"))
        fake_repo = FakeWalletRepository(wallet)
        gateway = FakeGateway(wallet=wallet)
        service = WalletService(session=fake_repo, gateway=gateway)
        service.repo = fake_repo

        transaction = await service.withdraw(
            user_id,
            WithdrawRequest(amount=Decimal("40.00"), destination=PixDestination(key="user@example.com")),
        )

        assert gateway.balance_at_payout_call == Decimal("60.00")
        assert wallet.balance == Decimal("60.00")
        assert transaction.balance_before == Decimal("100.00")
        assert transaction.balance_after == Decimal("60.00")

    async def test_raises_on_insufficient_funds(self, make_wallet):
        """Verify withdraw raises InsufficientFundsError when the balance is below the requested amount."""
        user_id = uuid.uuid4()
        wallet = make_wallet(user_id=user_id, balance=Decimal("5.00"))
        fake_repo = FakeWalletRepository(wallet)
        service = WalletService(session=fake_repo, gateway=FakeGateway())
        service.repo = fake_repo

        with pytest.raises(InsufficientFundsError):
            await service.withdraw(
                user_id,
                WithdrawRequest(amount=Decimal("10.00"), destination=PixDestination(key="user@example.com")),
            )

    async def test_releases_reservation_on_gateway_failure(self, make_wallet):
        """Verify a failed payout restores the reserved balance and marks the transaction FAILED."""
        user_id = uuid.uuid4()
        wallet = make_wallet(user_id=user_id, balance=Decimal("100.00"))
        fake_repo = FakeWalletRepository(wallet)
        service = WalletService(session=fake_repo, gateway=FakeGateway(should_fail=True))
        service.repo = fake_repo

        transaction = await service.withdraw(
            user_id,
            WithdrawRequest(amount=Decimal("40.00"), destination=PixDestination(key="user@example.com")),
        )

        assert transaction.status == TransactionStatus.FAILED
        assert wallet.balance == Decimal("100.00")


# ---------------------------------------------------------------------------
# Transfer tests
# ---------------------------------------------------------------------------

class TestTransfer:
    async def test_debit_and_credit_are_linked(self, make_wallet):
        """Verify transfer links the debit and credit transactions via counterpart_transaction_id."""
        sender_id = uuid.uuid4()
        sender_wallet = make_wallet(user_id=sender_id, balance=Decimal("100.00"))
        recipient_wallet = make_wallet(user_id=uuid.uuid4(), balance=Decimal("20.00"))
        fake_repo = FakeWalletRepository(sender_wallet, recipient_wallet=recipient_wallet)
        service = WalletService(session=fake_repo, gateway=FakeGateway())
        service.repo = fake_repo

        debit_tx, credit_tx = await service.transfer(
            sender_id, TransferRequest(amount=Decimal("30.00"), recipient_email="recipient@example.com")
        )

        assert debit_tx.counterpart_transaction_id == credit_tx.id
        assert credit_tx.counterpart_transaction_id == debit_tx.id

    async def test_total_supply_is_conserved(self, make_wallet):
        """Verify sender_balance_after + receiver_balance_after equals the combined balance before the transfer."""
        sender_id = uuid.uuid4()
        sender_wallet = make_wallet(user_id=sender_id, balance=Decimal("100.00"))
        recipient_wallet = make_wallet(user_id=uuid.uuid4(), balance=Decimal("20.00"))
        total_before = sender_wallet.balance + recipient_wallet.balance
        fake_repo = FakeWalletRepository(sender_wallet, recipient_wallet=recipient_wallet)
        service = WalletService(session=fake_repo, gateway=FakeGateway())
        service.repo = fake_repo

        debit_tx, credit_tx = await service.transfer(
            sender_id, TransferRequest(amount=Decimal("30.00"), recipient_email="recipient@example.com")
        )

        assert debit_tx.balance_after + credit_tx.balance_after == total_before

    async def test_raises_on_insufficient_funds(self, make_wallet):
        """Verify transfer raises InsufficientFundsError when the sender's balance is too low."""
        sender_id = uuid.uuid4()
        sender_wallet = make_wallet(user_id=sender_id, balance=Decimal("10.00"))
        recipient_wallet = make_wallet(user_id=uuid.uuid4())
        fake_repo = FakeWalletRepository(sender_wallet, recipient_wallet=recipient_wallet)
        service = WalletService(session=fake_repo, gateway=FakeGateway())
        service.repo = fake_repo

        with pytest.raises(InsufficientFundsError):
            await service.transfer(
                sender_id, TransferRequest(amount=Decimal("50.00"), recipient_email="recipient@example.com")
            )

    async def test_raises_when_recipient_not_found(self, make_wallet):
        """Verify transfer raises WalletNotFoundError when the recipient email has no matching wallet."""
        sender_id = uuid.uuid4()
        sender_wallet = make_wallet(user_id=sender_id, balance=Decimal("100.00"))
        fake_repo = FakeWalletRepository(sender_wallet, recipient_wallet=None)
        service = WalletService(session=fake_repo, gateway=FakeGateway())
        service.repo = fake_repo

        with pytest.raises(WalletNotFoundError):
            await service.transfer(
                sender_id, TransferRequest(amount=Decimal("10.00"), recipient_email="ghost@example.com")
            )
