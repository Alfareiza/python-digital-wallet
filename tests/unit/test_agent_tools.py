"""
Unit tests for the agent tools built by `build_tools(repo, user_id)`.

These tests must NOT use a real database or make real LLM/HTTP calls.
Use a fake/in-memory WalletRepository so each tool can be exercised in isolation.

The key property under test is DATA SCOPING: every tool must operate exclusively
on data belonging to the `user_id` the tools were built for (BUSINESS_SPEC A-04).
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.agent.tools import build_tools
from src.wallet.models import Transaction, TransactionStatus, TransactionType, Wallet, WalletStatus


# ---------------------------------------------------------------------------
# Fakes — implement these as part of your submission
# ---------------------------------------------------------------------------

class FakeWalletRepository:
    """In-memory replacement for WalletRepository, seeded with transactions
    belonging to more than one user so scoping can be verified."""

    def __init__(
        self,
        wallets: dict[uuid.UUID, Wallet] | None = None,
        transactions: list[Transaction] | None = None,
    ):
        """Seed the fake with wallets keyed by user_id and a flat list of transactions across wallets."""
        self.wallets_by_user = wallets or {}
        self.transactions = transactions or []

    async def get_by_user_id(self, user_id: uuid.UUID) -> Wallet | None:
        """Return the wallet seeded for user_id, or None if none was configured."""
        return self.wallets_by_user.get(user_id)

    def _matching(
        self,
        wallet_id: uuid.UUID,
        *,
        type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[Transaction]:
        """Filter the seeded transactions the same way WalletRepository._filtered_transactions would."""
        rows = [t for t in self.transactions if t.wallet_id == wallet_id]
        if type:
            rows = [t for t in rows if t.type == type]
        if status:
            rows = [t for t in rows if t.status == status]
        if start_date:
            rows = [t for t in rows if t.created_at >= start_date]
        if end_date:
            rows = [t for t in rows if t.created_at <= end_date]
        return rows

    async def list_transactions(
        self,
        wallet_id: uuid.UUID,
        *,
        page_size: int = 20,
        type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[list[Transaction], int]:
        """Mimic WalletRepository.list_transactions: filter, sort newest-first, and cap at page_size."""
        rows = sorted(
            self._matching(wallet_id, type=type, status=status, start_date=start_date, end_date=end_date),
            key=lambda t: t.created_at,
            reverse=True,
        )
        return rows[:page_size], len(rows)

    async def aggregate_transactions(
        self,
        wallet_id: uuid.UUID,
        *,
        operation: str,
        type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[Decimal | int | None, int]:
        """Mimic WalletRepository.aggregate_transactions: compute SUM/AVG/COUNT/MAX/MIN over matching rows."""
        amounts = [
            t.amount
            for t in self._matching(wallet_id, type=type, status=status, start_date=start_date, end_date=end_date)
        ]
        if operation == "COUNT":
            return len(amounts), len(amounts)
        if not amounts:
            return None, 0
        aggregates = {"SUM": sum(amounts), "AVG": sum(amounts) / len(amounts), "MAX": max(amounts), "MIN": min(amounts)}
        return aggregates[operation], len(amounts)

    async def get_top_transactions(
        self,
        wallet_id: uuid.UUID,
        *,
        n: int = 5,
        order: str = "largest",
        type: TransactionType | None = None,
        status: TransactionStatus | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[Transaction]:
        """Mimic WalletRepository.get_top_transactions: sort matching rows by amount and slice the top N."""
        rows = self._matching(wallet_id, type=type, status=status, start_date=start_date, end_date=end_date)
        rows.sort(key=lambda t: t.amount, reverse=(order == "largest"))
        return rows[:n]

    async def get_transaction(self, transaction_id: uuid.UUID, wallet_id: uuid.UUID) -> Transaction | None:
        """Return the seeded transaction only if both its id and wallet_id match."""
        for t in self.transactions:
            if t.id == transaction_id and t.wallet_id == wallet_id:
                return t
        return None


def _build_tool_map(repo: FakeWalletRepository, user_id: uuid.UUID) -> dict:
    """Build a name-indexed map of the tools returned by build_tools, for convenient lookup in tests."""
    return {tool.name: tool for tool in build_tools(repo, user_id)}


# ---------------------------------------------------------------------------
# get_wallet_summary
# ---------------------------------------------------------------------------

class TestGetWalletSummary:
    async def test_returns_balance_status_and_currency_for_the_user(self):
        """Verify get_wallet_summary returns the caller's own balance, currency, and status."""
        user_id = uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, balance=Decimal("150.50"), currency="BRL",
                         status=WalletStatus.ACTIVE)
        repo = FakeWalletRepository(wallets={user_id: wallet})
        tools = _build_tool_map(repo, user_id)

        result = await tools["get_wallet_summary"].ainvoke({})

        assert result == {"balance": "150.50", "currency": "BRL", "status": "ACTIVE"}

    async def test_handles_user_without_wallet(self):
        """Verify get_wallet_summary raises a clear error when the caller has no wallet."""
        repo = FakeWalletRepository()
        tools = _build_tool_map(repo, uuid.uuid4())

        with pytest.raises(ValueError, match="No wallet found"):
            await tools["get_wallet_summary"].ainvoke({})


# ---------------------------------------------------------------------------
# list_transactions
# ---------------------------------------------------------------------------

class TestListTransactions:
    async def test_only_returns_transactions_for_the_scoped_user(self):
        """Verify list_transactions never includes another user's transactions."""
        user_id, other_user_id = uuid.uuid4(), uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        other_wallet = Wallet(id=uuid.uuid4(), user_id=other_user_id, status=WalletStatus.ACTIVE)
        now = datetime.now(timezone.utc)
        own_tx = Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.DEPOSIT,
                              amount=Decimal("10.00"), status=TransactionStatus.COMPLETED, created_at=now)
        other_tx = Transaction(id=uuid.uuid4(), wallet_id=other_wallet.id, type=TransactionType.DEPOSIT,
                                amount=Decimal("999.00"), status=TransactionStatus.COMPLETED, created_at=now)
        repo = FakeWalletRepository(wallets={user_id: wallet, other_user_id: other_wallet},
                                     transactions=[own_tx, other_tx])
        tools = _build_tool_map(repo, user_id)

        result = await tools["list_transactions"].ainvoke({})

        assert {t["id"] for t in result["transactions"]} == {str(own_tx.id)}

    async def test_applies_type_and_status_filters(self):
        """Verify type and status arguments narrow the results to matching transactions only."""
        user_id = uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        now = datetime.now(timezone.utc)
        match = Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.WITHDRAWAL,
                             amount=Decimal("20.00"), status=TransactionStatus.COMPLETED, created_at=now)
        wrong_type = Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.DEPOSIT,
                                  amount=Decimal("20.00"), status=TransactionStatus.COMPLETED, created_at=now)
        wrong_status = Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.WITHDRAWAL,
                                    amount=Decimal("20.00"), status=TransactionStatus.PENDING, created_at=now)
        repo = FakeWalletRepository(wallets={user_id: wallet}, transactions=[match, wrong_type, wrong_status])
        tools = _build_tool_map(repo, user_id)

        result = await tools["list_transactions"].ainvoke({"type": "WITHDRAWAL", "status": "COMPLETED"})

        assert {t["id"] for t in result["transactions"]} == {str(match.id)}

    async def test_returns_empty_result_when_nothing_matches(self):
        """Verify list_transactions returns an empty list and total=0 when no transaction matches."""
        user_id = uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        repo = FakeWalletRepository(wallets={user_id: wallet})
        tools = _build_tool_map(repo, user_id)

        result = await tools["list_transactions"].ainvoke({})

        assert result == {"total": 0, "transactions": []}


# ---------------------------------------------------------------------------
# aggregate_transactions
# ---------------------------------------------------------------------------

class TestAggregateTransactions:
    async def test_sum_over_withdrawals(self):
        """Verify SUM aggregates only the matching (COMPLETED, WITHDRAWAL) transaction amounts."""
        user_id = uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        now = datetime.now(timezone.utc)
        withdrawals = [
            Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.WITHDRAWAL, amount=amount,
                        status=TransactionStatus.COMPLETED, created_at=now)
            for amount in (Decimal("10.00"), Decimal("15.00"))
        ]
        deposit = Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.DEPOSIT,
                               amount=Decimal("500.00"), status=TransactionStatus.COMPLETED, created_at=now)
        repo = FakeWalletRepository(wallets={user_id: wallet}, transactions=[*withdrawals, deposit])
        tools = _build_tool_map(repo, user_id)

        result = await tools["aggregate_transactions"].ainvoke({"operation": "sum", "type": "WITHDRAWAL"})

        assert result == {"operation": "SUM", "value": "25.00", "count": 2}

    async def test_count_and_avg(self):
        """Verify COUNT and AVG reflect the number and mean of the matching transactions."""
        user_id = uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        now = datetime.now(timezone.utc)
        transactions = [
            Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.DEPOSIT, amount=amount,
                        status=TransactionStatus.COMPLETED, created_at=now)
            for amount in (Decimal("10.00"), Decimal("20.00"), Decimal("30.00"))
        ]
        repo = FakeWalletRepository(wallets={user_id: wallet}, transactions=transactions)
        tools = _build_tool_map(repo, user_id)

        count_result = await tools["aggregate_transactions"].ainvoke({"operation": "count"})
        avg_result = await tools["aggregate_transactions"].ainvoke({"operation": "avg"})

        assert count_result == {"operation": "COUNT", "value": "3", "count": 3}
        assert avg_result == {"operation": "AVG", "value": "20.00", "count": 3}

    async def test_aggregation_is_scoped_to_user(self):
        """Verify aggregate_transactions never includes another user's transactions in the computation."""
        user_id, other_user_id = uuid.uuid4(), uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        other_wallet = Wallet(id=uuid.uuid4(), user_id=other_user_id, status=WalletStatus.ACTIVE)
        now = datetime.now(timezone.utc)
        own_tx = Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.DEPOSIT,
                              amount=Decimal("10.00"), status=TransactionStatus.COMPLETED, created_at=now)
        other_tx = Transaction(id=uuid.uuid4(), wallet_id=other_wallet.id, type=TransactionType.DEPOSIT,
                                amount=Decimal("1000.00"), status=TransactionStatus.COMPLETED, created_at=now)
        repo = FakeWalletRepository(wallets={user_id: wallet, other_user_id: other_wallet},
                                     transactions=[own_tx, other_tx])
        tools = _build_tool_map(repo, user_id)

        result = await tools["aggregate_transactions"].ainvoke({"operation": "sum"})

        assert result == {"operation": "SUM", "value": "10.00", "count": 1}


# ---------------------------------------------------------------------------
# get_top_transactions
# ---------------------------------------------------------------------------

class TestGetTopTransactions:
    async def test_returns_n_largest(self):
        """Verify order='largest' returns the top N transactions sorted highest amount first."""
        user_id = uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        now = datetime.now(timezone.utc)
        transactions = [
            Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.DEPOSIT, amount=amount,
                        status=TransactionStatus.COMPLETED, created_at=now)
            for amount in (Decimal("10.00"), Decimal("50.00"), Decimal("30.00"))
        ]
        repo = FakeWalletRepository(wallets={user_id: wallet}, transactions=transactions)
        tools = _build_tool_map(repo, user_id)

        result = await tools["get_top_transactions"].ainvoke({"n": 2, "order": "largest"})

        assert [t["amount"] for t in result["transactions"]] == ["50.00", "30.00"]

    async def test_returns_n_smallest(self):
        """Verify order='smallest' returns the top N transactions sorted lowest amount first."""
        user_id = uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        now = datetime.now(timezone.utc)
        transactions = [
            Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.DEPOSIT, amount=amount,
                        status=TransactionStatus.COMPLETED, created_at=now)
            for amount in (Decimal("10.00"), Decimal("50.00"), Decimal("30.00"))
        ]
        repo = FakeWalletRepository(wallets={user_id: wallet}, transactions=transactions)
        tools = _build_tool_map(repo, user_id)

        result = await tools["get_top_transactions"].ainvoke({"n": 2, "order": "smallest"})

        assert [t["amount"] for t in result["transactions"]] == ["10.00", "30.00"]


# ---------------------------------------------------------------------------
# get_transaction_detail
# ---------------------------------------------------------------------------

class TestGetTransactionDetail:
    async def test_returns_detail_for_owned_transaction(self):
        """Verify get_transaction_detail returns the full serialized transaction when owned by the caller."""
        user_id = uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        now = datetime.now(timezone.utc)
        transaction = Transaction(id=uuid.uuid4(), wallet_id=wallet.id, type=TransactionType.DEPOSIT,
                                   amount=Decimal("42.00"), status=TransactionStatus.COMPLETED, created_at=now)
        repo = FakeWalletRepository(wallets={user_id: wallet}, transactions=[transaction])
        tools = _build_tool_map(repo, user_id)

        result = await tools["get_transaction_detail"].ainvoke({"transaction_id": str(transaction.id)})

        assert result["id"] == str(transaction.id)
        assert result["amount"] == "42.00"

    async def test_refuses_transaction_belonging_to_another_user(self):
        """Verify get_transaction_detail raises instead of leaking a transaction owned by another user."""
        user_id, other_user_id = uuid.uuid4(), uuid.uuid4()
        wallet = Wallet(id=uuid.uuid4(), user_id=user_id, status=WalletStatus.ACTIVE)
        other_wallet = Wallet(id=uuid.uuid4(), user_id=other_user_id, status=WalletStatus.ACTIVE)
        now = datetime.now(timezone.utc)
        other_tx = Transaction(id=uuid.uuid4(), wallet_id=other_wallet.id, type=TransactionType.DEPOSIT,
                                amount=Decimal("999.00"), status=TransactionStatus.COMPLETED, created_at=now)
        repo = FakeWalletRepository(wallets={user_id: wallet, other_user_id: other_wallet}, transactions=[other_tx])
        tools = _build_tool_map(repo, user_id)

        with pytest.raises(ValueError, match="not found"):
            await tools["get_transaction_detail"].ainvoke({"transaction_id": str(other_tx.id)})
