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

    async def create(self, user_id: uuid.UUID) -> Wallet:
        """Insert a new wallet for the user, relying on model defaults (balance 0, ACTIVE)."""
        wallet = Wallet(user_id=user_id)
        self.session.add(wallet)
        await self.session.flush()
        return wallet

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

    def _filtered_transactions(
        self,
        wallet_id: uuid.UUID,
        *,
        type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        min_amount: Decimal | None = None,
        max_amount: Decimal | None = None,
    ):
        """Build the base filtered-by-wallet Transaction query shared by listing/aggregation/top-N."""
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
        return query

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
        query = self._filtered_transactions(
            wallet_id,
            type=type,
            status=status,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
        )
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.execute(
            query.order_by(Transaction.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.scalars().all()), total or 0

    async def aggregate_transactions(
        self,
        wallet_id: uuid.UUID,
        *,
        operation: str,
        type: TransactionType | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[Decimal | int | None, int]:
        """Compute a SUM/AVG/COUNT/MAX/MIN over a wallet's filtered transaction amounts, plus row count."""
        aggregate_fns = {"SUM": func.sum, "AVG": func.avg, "COUNT": func.count, "MAX": func.max, "MIN": func.min}
        if operation not in aggregate_fns:
            raise ValueError(f"Unsupported operation: {operation!r}. Use one of {sorted(aggregate_fns)}")

        subquery = self._filtered_transactions(
            wallet_id, type=type, start_date=start_date, end_date=end_date
        ).subquery()
        value = await self.session.scalar(select(aggregate_fns[operation](subquery.c.amount)))
        count = await self.session.scalar(select(func.count()).select_from(subquery))
        return value, count or 0

    async def get_top_transactions(
        self,
        wallet_id: uuid.UUID,
        *,
        n: int = 5,
        order: str = "largest",
        type: TransactionType | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[Transaction]:
        """Return the N largest or smallest transactions for a wallet matching the given filters."""
        sort = Transaction.amount.desc() if order == "largest" else Transaction.amount.asc()
        query = self._filtered_transactions(wallet_id, type=type, start_date=start_date, end_date=end_date)
        rows = await self.session.execute(query.order_by(sort).limit(n))
        return list(rows.scalars().all())
