import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.gateway.base import PaymentGateway
from src.wallet.models import Transaction, TransactionStatus, TransactionType, Wallet, WalletStatus
from src.wallet.repository import WalletRepository
from src.wallet.schemas import DepositRequest, TransferRequest, WithdrawRequest


class InsufficientFundsError(Exception):
    pass


class WalletNotFoundError(Exception):
    pass


class WalletFrozenError(Exception):
    pass


class TransactionNotFoundError(Exception):
    pass


class WalletService:
    def __init__(self, session: AsyncSession, gateway: PaymentGateway):
        self.repo = WalletRepository(session)
        self.session = session
        self.gateway = gateway

    async def get_wallet(self, user_id: uuid.UUID) -> Wallet:
        """Fetch the current user's wallet, raising if none exists."""
        wallet = await self.repo.get_by_user_id(user_id)
        if not wallet:
            raise WalletNotFoundError(f"No wallet found for user {user_id}")
        return wallet

    async def get_or_create_wallet(self, user_id: uuid.UUID) -> tuple[Wallet, bool]:
        """Fetch the user's wallet, creating one (balance 0, ACTIVE) if none exists yet.

        Returns (wallet, created) so callers can distinguish a fresh wallet from an existing one.
        """
        try:
            return await self.get_wallet(user_id), False
        except WalletNotFoundError:
            wallet = await self.repo.create(user_id)
            await self.session.commit()
            await self.session.refresh(wallet)
            return wallet, True

    async def deposit(self, user_id: uuid.UUID, request: DepositRequest) -> Transaction:
        """Create a pending deposit transaction and request a payment intent from the gateway."""
        wallet = await self.get_wallet(user_id)
        self._assert_active(wallet)

        transaction = await self.repo.create_transaction(
            wallet_id=wallet.id,
            type=TransactionType.DEPOSIT,
            amount=request.amount,
            balance_before=wallet.balance,
            balance_after=wallet.balance,
            status=TransactionStatus.PENDING,
            description=request.description,
        )

        try:
            intent = await self.gateway.create_deposit_intent(
                amount=request.amount,
                currency=request.currency,
                metadata={"transaction_id": str(transaction.id), "wallet_id": str(wallet.id)},
            )
        except Exception:
            # D-04: gateway failure never touches the balance, only marks the transaction FAILED.
            transaction.status = TransactionStatus.FAILED
            await self.session.commit()
            await self.session.refresh(transaction)
            return transaction

        transaction.gateway_reference = intent.gateway_reference
        transaction.extra_data = {"client_secret": intent.client_secret, "gateway_status": intent.status}
        await self.session.commit()
        await self.session.refresh(transaction)
        return transaction

    async def withdraw(self, user_id: uuid.UUID, request: WithdrawRequest) -> Transaction:
        """Reserve funds immediately (debit) and request a payout from the gateway."""
        wallet = await self.get_wallet(user_id)
        locked_wallet = await self.repo.get_for_update(wallet.id)
        self._assert_active(locked_wallet)
        if locked_wallet.balance < request.amount:
            raise InsufficientFundsError(f"Wallet {wallet.id} has insufficient funds")

        balance_before = locked_wallet.balance
        locked_wallet.balance -= request.amount
        transaction = await self.repo.create_transaction(
            wallet_id=locked_wallet.id,
            type=TransactionType.WITHDRAWAL,
            amount=request.amount,
            balance_before=balance_before,
            balance_after=locked_wallet.balance,
            status=TransactionStatus.PENDING,
            description=request.description,
        )
        await self.session.commit()

        try:
            intent = await self.gateway.create_payout(
                amount=request.amount,
                destination=request.destination.model_dump(),
                metadata={
                    "transaction_id": str(transaction.id),
                    "wallet_id": str(locked_wallet.id),
                    "currency": locked_wallet.currency,
                },
            )
        except Exception:
            # S-04: release the reservation and mark FAILED when the gateway rejects the payout.
            refreshed_wallet = await self.repo.get_for_update(locked_wallet.id)
            refreshed_wallet.balance += request.amount
            transaction.status = TransactionStatus.FAILED
            await self.session.commit()
            await self.session.refresh(transaction)
            return transaction

        transaction.gateway_reference = intent.gateway_reference
        transaction.extra_data = {
            "gateway_status": intent.status,
            "destination": request.destination.model_dump(),
        }
        await self.session.commit()
        await self.session.refresh(transaction)
        return transaction

    async def transfer(self, sender_user_id: uuid.UUID, request: TransferRequest) -> tuple[Transaction, Transaction]:
        """Atomically debit the sender and credit the recipient, linking both transactions."""
        sender_wallet = await self.get_wallet(sender_user_id)

        result = await self.session.execute(
            select(Wallet).join(User, User.id == Wallet.user_id).where(User.email == request.recipient_email)
        )
        recipient_wallet = result.scalar_one_or_none()
        if recipient_wallet is None:
            raise WalletNotFoundError(f"No wallet found for recipient {request.recipient_email}")

        # Lock both wallets in a consistent (ascending id) order to avoid deadlocks.
        first_id, second_id = sorted([sender_wallet.id, recipient_wallet.id])
        locked_first = await self.repo.get_for_update(first_id)
        locked_second = locked_first if second_id == first_id else await self.repo.get_for_update(second_id)
        locked_sender = locked_first if locked_first.id == sender_wallet.id else locked_second
        locked_recipient = locked_first if locked_first.id == recipient_wallet.id else locked_second

        self._assert_active(locked_sender)
        self._assert_active(locked_recipient)
        if locked_sender.balance < request.amount:
            raise InsufficientFundsError(f"Wallet {locked_sender.id} has insufficient funds")

        sender_balance_before = locked_sender.balance
        locked_sender.balance -= request.amount
        recipient_balance_before = locked_recipient.balance
        locked_recipient.balance += request.amount

        debit_tx = await self.repo.create_transaction(
            wallet_id=locked_sender.id,
            type=TransactionType.TRANSFER_DEBIT,
            amount=request.amount,
            balance_before=sender_balance_before,
            balance_after=locked_sender.balance,
            status=TransactionStatus.COMPLETED,
            description=request.description,
        )
        credit_tx = await self.repo.create_transaction(
            wallet_id=locked_recipient.id,
            type=TransactionType.TRANSFER_CREDIT,
            amount=request.amount,
            balance_before=recipient_balance_before,
            balance_after=locked_recipient.balance,
            status=TransactionStatus.COMPLETED,
            description=request.description,
            counterpart_transaction_id=debit_tx.id,
        )
        debit_tx.counterpart_transaction_id = credit_tx.id

        await self.session.commit()
        await self.session.refresh(debit_tx)
        await self.session.refresh(credit_tx)
        return debit_tx, credit_tx

    async def list_transactions(
        self,
        user_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
    ) -> tuple[list[Transaction], int]:
        """List the current user's transactions with pagination and optional filters."""
        wallet = await self.get_wallet(user_id)
        return await self.repo.list_transactions(
            wallet.id,
            page=page,
            page_size=page_size,
            type=type,
            status=status,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
        )

    async def get_transaction(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> Transaction:
        """Fetch a single transaction belonging to the current user's wallet."""
        wallet = await self.get_wallet(user_id)
        transaction = await self.repo.get_transaction(transaction_id, wallet.id)
        if transaction is None:
            raise TransactionNotFoundError(f"No transaction {transaction_id} for wallet {wallet.id}")
        return transaction

    async def confirm_deposit(self, gateway_reference: str, succeeded: bool) -> Transaction | None:
        """Apply a gateway deposit confirmation/failure idempotently (D-03, D-05, TECHNICAL_SPEC 4.4)."""
        transaction = await self.repo.get_by_gateway_reference(gateway_reference)
        if transaction is None:
            return None
        if transaction.status in (TransactionStatus.COMPLETED, TransactionStatus.FAILED):
            return transaction  # already terminal — idempotent no-op

        if succeeded:
            locked_wallet = await self.repo.get_for_update(transaction.wallet_id)
            transaction.balance_before = locked_wallet.balance
            locked_wallet.balance += transaction.amount
            transaction.balance_after = locked_wallet.balance
            transaction.status = TransactionStatus.COMPLETED
        else:
            transaction.status = TransactionStatus.FAILED

        await self.session.commit()
        await self.session.refresh(transaction)
        return transaction

    async def confirm_payout(self, gateway_reference: str, succeeded: bool) -> Transaction | None:
        """Apply a gateway payout confirmation/failure idempotently, releasing the reservation on failure (S-04)."""
        transaction = await self.repo.get_by_gateway_reference(gateway_reference)
        if transaction is None:
            return None
        if transaction.status in (TransactionStatus.COMPLETED, TransactionStatus.FAILED):
            return transaction  # already terminal — idempotent no-op

        if succeeded:
            transaction.status = TransactionStatus.COMPLETED
        else:
            locked_wallet = await self.repo.get_for_update(transaction.wallet_id)
            locked_wallet.balance += transaction.amount
            transaction.status = TransactionStatus.FAILED

        await self.session.commit()
        await self.session.refresh(transaction)
        return transaction

    def _assert_active(self, wallet: Wallet) -> None:
        if wallet.status == WalletStatus.FROZEN:
            raise WalletFrozenError("Wallet is frozen")
        if wallet.status == WalletStatus.CLOSED:
            raise WalletFrozenError("Wallet is closed")
