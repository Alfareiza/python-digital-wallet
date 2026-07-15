from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session

router = APIRouter()


@router.post("/webhooks/gateway", status_code=status.HTTP_200_OK)
async def receive_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    # TODO: implement webhook processing
    raw_body = await request.body()
    raise NotImplementedError
