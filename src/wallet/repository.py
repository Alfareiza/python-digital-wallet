import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.wallet.models import Transaction, TransactionStatus, TransactionType, Wallet


class WalletRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: uuid.UUID) -> Wallet | None:
        result = await self.session.execute(select(Wallet).where(Wallet.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_for_update(self, wallet_id: uuid.UUID) -> Wallet | None:
        """Acquires a row-level lock. Caller must be inside an open transaction."""
        result = await self.session.execute(
            select(Wallet).where(Wallet.id == wallet_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def create_transaction(self, **kwargs) -> Transaction:
        tx = Transaction(**kwargs)
        self.session.add(tx)
        await self.session.flush()
        return tx

    async def get_transaction(self, transaction_id: uuid.UUID, wallet_id: uuid.UUID) -> Transaction | None:
        result = await self.session.execute(
            select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.wallet_id == wallet_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_gateway_reference(self, gateway_reference: str) -> Transaction | None:
        result = await self.session.execute(
            select(Transaction).where(Transaction.gateway_reference == gateway_reference)
        )
        return result.scalar_one_or_none()

    async def list_transactions(
        self,
        wallet_id: uuid.UUID,
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
        """List a wallet's transactions with pagination and optional type/status/date/amount filters."""
        query = select(Transaction).where(Transaction.wallet_id == wallet_id)
        if type:
            query = query.where(Transaction.type == type)
        if status:
            query = query.where(Transaction.status == status)
        if start_date:
            query = query.where(Transaction.created_at >= start_date)
        if end_date:
            query = query.where(Transaction.created_at <= end_date)
        if min_amount is not None:
            query = query.where(Transaction.amount >= min_amount)
        if max_amount is not None:
            query = query.where(Transaction.amount <= max_amount)

        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.execute(
            query.order_by(Transaction.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.scalars().all()), total or 0
