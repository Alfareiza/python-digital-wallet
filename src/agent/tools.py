import uuid
from datetime import datetime
from typing import Optional

from langchain_core.tools import BaseTool, tool

from src.wallet.models import Transaction, TransactionStatus, TransactionType
from src.wallet.repository import WalletRepository


def _serialize_transaction(transaction: Transaction) -> dict:
    """Convert a Transaction row into a JSON-friendly dict for tool results."""
    return {
        "id": str(transaction.id),
        "type": transaction.type,
        "amount": str(transaction.amount),
        "status": transaction.status,
        "description": transaction.description,
        "counterpart_transaction_id": (
            str(transaction.counterpart_transaction_id) if transaction.counterpart_transaction_id else None
        ),
        "gateway_reference": transaction.gateway_reference,
        "created_at": transaction.created_at.isoformat(),
    }


def build_tools(repo: WalletRepository, user_id: uuid.UUID) -> list[BaseTool]:
    """
    Returns a list of LangChain tools scoped to a specific user.
    All tool queries must operate exclusively on data belonging to user_id.
    """

    async def _get_wallet():
        """Fetch the caller's wallet or raise so the agent loop reports it as a graceful tool error."""
        wallet = await repo.get_by_user_id(user_id)
        if wallet is None:
            raise ValueError("No wallet found for this user")
        return wallet

    @tool
    async def get_wallet_summary() -> dict:
        """Returns the current wallet balance, status, and metadata."""
        wallet = await _get_wallet()
        return {"balance": str(wallet.balance), "currency": wallet.currency, "status": wallet.status}

    @tool
    async def list_transactions(
        type: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        """
        Returns a paginated list of transactions.
        type: DEPOSIT | WITHDRAWAL | TRANSFER_DEBIT | TRANSFER_CREDIT
        status: PENDING | COMPLETED | FAILED | REVERSED
        start_date / end_date: ISO 8601 date strings (e.g. '2026-01-01')
        """
        wallet = await _get_wallet()
        transactions, total = await repo.list_transactions(
            wallet.id,
            page_size=limit,
            type=TransactionType(type) if type else None,
            status=TransactionStatus(status) if status else TransactionStatus.COMPLETED,
            start_date=datetime.fromisoformat(start_date) if start_date else None,
            end_date=datetime.fromisoformat(end_date) if end_date else None,
        )
        return {"total": total, "transactions": [_serialize_transaction(t) for t in transactions]}

    @tool
    async def aggregate_transactions(
        operation: str,
        type: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Computes an aggregation over the user's transactions (defaults to COMPLETED status).
        operation: SUM | AVG | COUNT | MAX | MIN
        type: optional transaction type filter
        status: PENDING | COMPLETED | FAILED | REVERSED (defaults to COMPLETED)
        """
        wallet = await _get_wallet()
        value, count = await repo.aggregate_transactions(
            wallet.id,
            operation=operation.upper(),
            type=TransactionType(type) if type else None,
            status=TransactionStatus(status) if status else TransactionStatus.COMPLETED,
            start_date=datetime.fromisoformat(start_date) if start_date else None,
            end_date=datetime.fromisoformat(end_date) if end_date else None,
        )
        return {"operation": operation.upper(), "value": str(value) if value is not None else None, "count": count}

    @tool
    async def get_top_transactions(
        n: int = 5,
        order: str = "largest",
        type: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Returns the N largest or smallest transactions (defaults to COMPLETED status).
        order: 'largest' | 'smallest'
        status: PENDING | COMPLETED | FAILED | REVERSED (defaults to COMPLETED)
        """
        wallet = await _get_wallet()
        transactions = await repo.get_top_transactions(
            wallet.id,
            n=n,
            order=order,
            type=TransactionType(type) if type else None,
            status=TransactionStatus(status) if status else TransactionStatus.COMPLETED,
            start_date=datetime.fromisoformat(start_date) if start_date else None,
            end_date=datetime.fromisoformat(end_date) if end_date else None,
        )
        return {"transactions": [_serialize_transaction(t) for t in transactions]}

    @tool
    async def get_transaction_detail(transaction_id: str) -> dict:
        """Returns full details of a single transaction by its UUID."""
        wallet = await _get_wallet()
        transaction = await repo.get_transaction(uuid.UUID(transaction_id), wallet.id)
        if transaction is None:
            raise ValueError(f"Transaction {transaction_id} not found")
        return _serialize_transaction(transaction)

    return [
        get_wallet_summary,
        list_transactions,
        aggregate_transactions,
        get_top_transactions,
        get_transaction_detail,
    ]
