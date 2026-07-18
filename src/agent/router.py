import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.agent import chat
from src.agent.session import session_store
from src.agent.tools import build_tools
from src.auth.models import User
from src.auth.service import get_current_user
from src.database import get_session
from src.wallet.repository import WalletRepository

router = APIRouter()

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str
    session_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    answer: str


class SessionResponse(BaseModel):
    session_id: uuid.UUID
    messages: list[dict]


@router.post("/chat", response_model=ChatResponse)
async def agent_chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Answer a natural-language question using tools scoped to the caller's own wallet data."""
    conversation = session_store.get_or_create(body.session_id, current_user.id)
    tools = build_tools(WalletRepository(session), current_user.id)
    logger.info(f"Agent chat request: user={current_user.id} session={conversation.id}")
    answer = await chat(body.message, conversation, tools)
    return ChatResponse(session_id=conversation.id, answer=answer)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session_history(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
):
    """Return a conversation's message history, if it belongs to the current user."""
    conversation = session_store.get(session_id)
    if conversation is None or conversation.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    messages = [{"role": message.type, "content": message.content} for message in conversation.messages]
    return SessionResponse(session_id=conversation.id, messages=messages)
