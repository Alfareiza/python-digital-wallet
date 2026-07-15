"""
Unit tests for the agent tools built by `build_tools(repo, user_id)`.

These tests must NOT use a real database or make real LLM/HTTP calls.
Use a fake/in-memory WalletRepository so each tool can be exercised in isolation.

The key property under test is DATA SCOPING: every tool must operate exclusively
on data belonging to the `user_id` the tools were built for (BUSINESS_SPEC A-04).
"""
import uuid

import pytest


# ---------------------------------------------------------------------------
# Fakes — implement these as part of your submission
# ---------------------------------------------------------------------------

class FakeWalletRepository:
    """In-memory replacement for WalletRepository, seeded with transactions
    belonging to more than one user so scoping can be verified."""
    pass


# ---------------------------------------------------------------------------
# get_wallet_summary
# ---------------------------------------------------------------------------

class TestGetWalletSummary:
    async def test_returns_balance_status_and_currency_for_the_user(self):
        # Arrange: build_tools(repo, user_id) for a user with an active wallet
        # Act: invoke the get_wallet_summary tool
        # Assert: returns balance, status and currency of THAT user's wallet
        pytest.skip("not implemented")

    async def test_handles_user_without_wallet(self):
        pytest.skip("not implemented")


# ---------------------------------------------------------------------------
# list_transactions
# ---------------------------------------------------------------------------

class TestListTransactions:
    async def test_only_returns_transactions_for_the_scoped_user(self):
        # Seed transactions for user A and user B; build tools for user A
        # Assert: none of user B's transactions are returned
        pytest.skip("not implemented")

    async def test_applies_type_and_status_filters(self):
        pytest.skip("not implemented")

    async def test_returns_empty_result_when_nothing_matches(self):
        pytest.skip("not implemented")


# ---------------------------------------------------------------------------
# aggregate_transactions
# ---------------------------------------------------------------------------

class TestAggregateTransactions:
    async def test_sum_over_withdrawals(self):
        pytest.skip("not implemented")

    async def test_count_and_avg(self):
        pytest.skip("not implemented")

    async def test_aggregation_is_scoped_to_user(self):
        pytest.skip("not implemented")


# ---------------------------------------------------------------------------
# get_top_transactions
# ---------------------------------------------------------------------------

class TestGetTopTransactions:
    async def test_returns_n_largest(self):
        pytest.skip("not implemented")

    async def test_returns_n_smallest(self):
        pytest.skip("not implemented")


# ---------------------------------------------------------------------------
# get_transaction_detail
# ---------------------------------------------------------------------------

class TestGetTransactionDetail:
    async def test_returns_detail_for_owned_transaction(self):
        pytest.skip("not implemented")

    async def test_refuses_transaction_belonging_to_another_user(self):
        # Requesting another user's transaction id must NOT leak its data
        pytest.skip("not implemented")
