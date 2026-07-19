import logging

from src.wallet.models import Transaction, TransactionStatus

logger = logging.getLogger(__name__)


def log_transaction_created(transaction: Transaction, *, reason: str) -> None:
    """Emit a structured log when a transaction is created with its initial status."""
    logger.info(
        f"transaction_state_change "
        f"event=created "
        f"transaction_id={transaction.id} "
        f"wallet_id={transaction.wallet_id} "
        f"type={transaction.type} "
        f"status={transaction.status} "
        f"amount={transaction.amount} "
        f"balance_before={transaction.balance_before} "
        f"balance_after={transaction.balance_after} "
        f"gateway_reference={transaction.gateway_reference} "
        f"reason={reason}"
    )


def log_transaction_status_change(
    transaction: Transaction,
    *,
    previous_status: TransactionStatus | str,
    reason: str,
) -> None:
    """Emit a structured log when a transaction transitions to a new status."""
    logger.info(
        f"transaction_state_change "
        f"event=status_changed "
        f"transaction_id={transaction.id} "
        f"wallet_id={transaction.wallet_id} "
        f"type={transaction.type} "
        f"previous_status={previous_status} "
        f"new_status={transaction.status} "
        f"amount={transaction.amount} "
        f"balance_before={transaction.balance_before} "
        f"balance_after={transaction.balance_after} "
        f"gateway_reference={transaction.gateway_reference} "
        f"reason={reason}"
    )


def log_transaction_idempotent_skip(transaction: Transaction, *, reason: str) -> None:
    """Emit a structured log when a duplicate confirmation is ignored."""
    logger.info(
        f"transaction_state_change "
        f"event=idempotent_skip "
        f"transaction_id={transaction.id} "
        f"wallet_id={transaction.wallet_id} "
        f"type={transaction.type} "
        f"status={transaction.status} "
        f"gateway_reference={transaction.gateway_reference} "
        f"reason={reason}"
    )
