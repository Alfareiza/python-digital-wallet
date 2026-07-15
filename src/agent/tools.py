import uuid
from typing import Optional

from langchain_core.tools import BaseTool, tool

from src.wallet.repository import WalletRepository


def build_tools(repo: WalletRepository, user_id: uuid.UUID) -> list[BaseTool]:
    """
    Returns a list of LangChain tools scoped to a specific user.
    All tool queries must operate exclusively on data belonging to user_id.
    """

    @tool
    async def get_wallet_summary() -> dict:
        """Returns the current wallet balance, status, and metadata."""
        # TODO: implement — fetch wallet by user_id
        raise NotImplementedError

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
        # TODO: implement — query transactions scoped to user_id
        raise NotImplementedError

    @tool
    async def aggregate_transactions(
        operation: str,
        type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Computes an aggregation over the user's transactions.
        operation: SUM | AVG | COUNT | MAX | MIN
        type: optional transaction type filter
        """
        # TODO: implement — run aggregation scoped to user_id
        raise NotImplementedError

    @tool
    async def get_top_transactions(
        n: int = 5,
        order: str = "largest",
        type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """
        Returns the N largest or smallest transactions.
        order: 'largest' | 'smallest'
        """
        # TODO: implement — query top-N transactions scoped to user_id
        raise NotImplementedError

    @tool
    async def get_transaction_detail(transaction_id: str) -> dict:
        """Returns full details of a single transaction by its UUID."""
        # TODO: implement — fetch transaction and verify it belongs to user_id
        raise NotImplementedError

    return [
        get_wallet_summary,
        list_transactions,
        aggregate_transactions,
        get_top_transactions,
        get_transaction_detail,
    ]
