import uuid

from sqlalchemy.ext.asyncio import AsyncSession

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


class WalletService:
    def __init__(self, session: AsyncSession, gateway: PaymentGateway):
        self.repo = WalletRepository(session)
        self.session = session
        self.gateway = gateway

    async def get_wallet(self, user_id: uuid.UUID) -> Wallet:
        wallet = await self.repo.get_by_user_id(user_id)
        if not wallet:
            raise WalletNotFoundError(f"No wallet found for user {user_id}")
        return wallet

    async def deposit(self, user_id: uuid.UUID, request: DepositRequest) -> Transaction:
        # TODO: implement deposit flow
        raise NotImplementedError

    async def withdraw(self, user_id: uuid.UUID, request: WithdrawRequest) -> Transaction:
        # TODO: implement withdrawal flow
        raise NotImplementedError

    async def transfer(self, sender_user_id: uuid.UUID, request: TransferRequest) -> tuple[Transaction, Transaction]:
        # TODO: implement peer-to-peer transfer
        raise NotImplementedError

    def _assert_active(self, wallet: Wallet) -> None:
        if wallet.status == WalletStatus.FROZEN:
            raise WalletFrozenError("Wallet is frozen")
        if wallet.status == WalletStatus.CLOSED:
            raise WalletFrozenError("Wallet is closed")
