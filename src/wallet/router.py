import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BeforeValidator
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.models import User
from src.auth.service import get_current_user
from src.config import settings
from src.database import get_session
from src.gateway.base import PaymentGateway
from src.gateway.stripe_gateway import StripeGateway
from src.wallet.models import TransactionStatus, TransactionType
from src.wallet.schemas import (
    DepositRequest,
    TransactionListResponse,
    TransactionResponse,
    TransferRequest,
    WalletResponse,
    WithdrawRequest,
)
from src.wallet.service import (
    InsufficientFundsError,
    TransactionNotFoundError,
    WalletFrozenError,
    WalletNotFoundError,
    WalletService,
)

router = APIRouter()

logger = logging.getLogger(__name__)

DATE_FORMAT = "%d/%m/%Y"


def _parse_start_date(value: str | datetime | None) -> datetime | None:
    """Parse a DD/MM/YYYY `start_date` query param as the beginning of that day (00:00:00 UTC)."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(value, DATE_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f"start_date must be in {DATE_FORMAT} format") from exc


def _parse_end_date(value: str | datetime | None) -> datetime | None:
    """Parse a DD/MM/YYYY `end_date` query param as the end of that day (23:59:59.999999 UTC)."""
    if value is None or isinstance(value, datetime):
        return value
    try:
        parsed = datetime.strptime(value, DATE_FORMAT)
    except ValueError as exc:
        raise ValueError(f"end_date must be in {DATE_FORMAT} format") from exc
    return parsed.replace(hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)


StartDateQuery = Annotated[
    datetime | None, BeforeValidator(_parse_start_date), Query(description="Format: DD/MM/YYYY")
]
EndDateQuery = Annotated[datetime | None, BeforeValidator(_parse_end_date), Query(description="Format: DD/MM/YYYY")]


def get_gateway() -> PaymentGateway:
    """Resolve the configured payment gateway (only Stripe is currently supported)."""
    if settings.gateway_provider != "stripe":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Unsupported gateway_provider: {settings.gateway_provider}",
        )
    return StripeGateway(
        settings.stripe_secret_key,
        settings.stripe_webhook_secret,
        simulate_payouts=settings.stripe_simulate_payouts,
    )


def get_wallet_service(
    session: AsyncSession = Depends(get_session),
    gateway: PaymentGateway = Depends(get_gateway),
) -> WalletService:
    return WalletService(session, gateway)


@router.get("/wallet", response_model=WalletResponse)
@router.post("/wallet", response_model=WalletResponse)
async def get_wallet(
    response: Response,
    current_user: User = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
):
    """Return the current user's wallet, creating one (balance 0, ACTIVE) if it doesn't exist yet."""
    logger.info(f"User {current_user.id} requesting wallet info")
    wallet, created = await service.get_or_create_wallet(current_user.id)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return wallet


@router.post("/wallet/deposit", response_model=TransactionResponse, status_code=status.HTTP_202_ACCEPTED)
async def deposit(
    body: DepositRequest,
    current_user: User = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
):
    """Initiate a deposit into the current user's wallet via the payment gateway."""
    try:
        return await service.deposit(current_user.id, body)
    except WalletNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WalletFrozenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/wallet/withdraw", response_model=TransactionResponse, status_code=status.HTTP_202_ACCEPTED)
async def withdraw(
    body: WithdrawRequest,
    current_user: User = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
):
    """Initiate a withdrawal from the current user's wallet via the payment gateway."""
    try:
        return await service.withdraw(current_user.id, body)
    except WalletNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WalletFrozenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InsufficientFundsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/wallet/transfer", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def transfer(
    body: TransferRequest,
    current_user: User = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
):
    """Transfer funds from the current user's wallet to another user's wallet, identified by email or user id."""
    try:
        debit_transaction, _credit_transaction = await service.transfer(current_user.id, body)
        return debit_transaction
    except WalletNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WalletFrozenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except InsufficientFundsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    type: TransactionType | None = Query(default=None),
    status_filter: TransactionStatus | None = Query(default=None, alias="status"),
    start_date: StartDateQuery = None,
    end_date: EndDateQuery = None,
    min_amount: Decimal | None = Query(default=None),
    max_amount: Decimal | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
):
    """List the current user's transactions, paginated and optionally filtered."""
    try:
        items, total = await service.list_transactions(
            current_user.id,
            page=page,
            page_size=page_size,
            type=type,
            status=status_filter,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
        )
    except WalletNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TransactionListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
):
    """Fetch a single transaction belonging to the current user's wallet."""
    try:
        return await service.get_transaction(current_user.id, transaction_id)
    except (WalletNotFoundError, TransactionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/confirm-payout/{gateway_reference}", response_model=TransactionResponse)
async def test_confirm_payout(
    gateway_reference: str,
    current_user: User = Depends(get_current_user),
    service: WalletService = Depends(get_wallet_service),
):
    """[TEST ONLY] Complete a pending simulated payout (development/testing).

    Use after POST /wallet/withdraw when STRIPE_SIMULATE_PAYOUTS=true (the default).
    Mirrors the deposit flow where POST /confirm-payment/{gateway_reference} completes
    a pending PaymentIntent.
    """
    try:
        wallet = await service.get_wallet(current_user.id)
        transaction = await service.repo.get_by_gateway_reference(gateway_reference)
        if transaction is None or transaction.wallet_id != wallet.id:
            raise TransactionNotFoundError(f"No transaction for gateway reference {gateway_reference}")
        return await service.confirm_payout(gateway_reference, succeeded=True)
    except WalletNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TransactionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/confirm-payment/{gateway_reference}", status_code=status.HTTP_200_OK)
async def test_confirm_payment(
    gateway_reference: str,
    current_user: User = Depends(get_current_user),
    gateway: PaymentGateway = Depends(get_gateway),
):
    """[TEST ONLY] Confirm a pending Stripe PaymentIntent to simulate customer payment (development/testing).
    
    Using curl, this is the snippet to call the same stripe endpoint
    curl -X POST https://api.stripe.com/v1/payment_intents/pi_3TtzE6EVk7D7KBoh1N0h99Dk/confirm 
    -H "Authorization: Bearer xyz" -d "payment_method=pm_card_visa" -d "return_url=http://localhost:8000/return"
    """
    import httpx

    async with httpx.AsyncClient(auth=(settings.stripe_secret_key, "")) as client:
        response = await client.post(
            f"https://api.stripe.com/v1/payment_intents/{gateway_reference}/confirm",
            data={"payment_method": "pm_card_visa", "return_url": "https://example.com/return"},
        )
    response.raise_for_status()
    return response.json()

