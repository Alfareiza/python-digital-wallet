import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.gateway.base import PaymentGateway
from src.wallet.router import get_gateway
from src.wallet.service import WalletService

router = APIRouter()

logger = logging.getLogger(__name__)

DEPOSIT_EVENTS = {"payment_intent.succeeded": True, "payment_intent.payment_failed": False}
PAYOUT_EVENTS = {"payout.paid": True, "payout.failed": False}


@router.post("/webhooks/gateway", status_code=status.HTTP_200_OK)
async def receive_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    gateway: PaymentGateway = Depends(get_gateway),
):
    """Verify a gateway webhook signature and apply the corresponding transaction outcome, idempotently."""
    raw_body = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        event = gateway.verify_webhook(raw_body, signature)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    event_type = event.get("type", "")
    gateway_reference = event.get("data", {}).get("object", {}).get("id", "")

    service = WalletService(session, gateway)
    if event_type in DEPOSIT_EVENTS:
        transaction = await service.confirm_deposit(gateway_reference, succeeded=DEPOSIT_EVENTS[event_type])
    elif event_type in PAYOUT_EVENTS:
        transaction = await service.confirm_payout(gateway_reference, succeeded=PAYOUT_EVENTS[event_type])
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unhandled event type: {event_type}")

    if transaction is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No transaction found for gateway reference {gateway_reference}",
        )

    logger.info(f"Processed {event_type} for transaction {transaction.id} (status={transaction.status})")
    return {"received": True}
