import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.gateway.base import PaymentGateway
from src.wallet.schemas import (
    DepositRequest,
    TransactionListResponse,
    TransactionResponse,
    TransferRequest,
    WalletResponse,
    WithdrawRequest,
)
from src.wallet.service import InsufficientFundsError, WalletFrozenError, WalletNotFoundError, WalletService

router = APIRouter()


def get_gateway() -> PaymentGateway:
    # TODO: return the correct gateway instance based on settings.gateway_provider
    raise NotImplementedError


def get_wallet_service(
    session: AsyncSession = Depends(get_session),
    gateway: PaymentGateway = Depends(get_gateway),
) -> WalletService:
    return WalletService(session, gateway)


@router.get("/wallet", response_model=WalletResponse)
async def get_wallet(
    service: WalletService = Depends(get_wallet_service),
):
    # TODO: identify the current user and call service.get_wallet(user_id)
    raise NotImplementedError


@router.post("/wallet/deposit", response_model=TransactionResponse, status_code=status.HTTP_202_ACCEPTED)
async def deposit(
    body: DepositRequest,
    service: WalletService = Depends(get_wallet_service),
):
    # TODO: identify the current user and call service.deposit(user_id, body)
    raise NotImplementedError


@router.post("/wallet/withdraw", response_model=TransactionResponse, status_code=status.HTTP_202_ACCEPTED)
async def withdraw(
    body: WithdrawRequest,
    service: WalletService = Depends(get_wallet_service),
):
    # TODO: identify the current user and call service.withdraw(user_id, body)
    raise NotImplementedError


@router.post("/wallet/transfer", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def transfer(
    body: TransferRequest,
    service: WalletService = Depends(get_wallet_service),
):
    # TODO: identify the current user and call service.transfer(user_id, body)
    raise NotImplementedError


@router.get("/transactions", response_model=TransactionListResponse)
async def list_transactions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    service: WalletService = Depends(get_wallet_service),
):
    # TODO: identify the current user and list their transactions
    raise NotImplementedError


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: uuid.UUID,
    service: WalletService = Depends(get_wallet_service),
):
    # TODO: identify the current user and fetch the transaction
    raise NotImplementedError
