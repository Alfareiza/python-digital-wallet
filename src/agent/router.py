import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.agent import chat
from src.agent.session import ConversationSession, session_store
from src.agent.tools import build_tools
from src.database import get_session
from src.wallet.repository import WalletRepository

router = APIRouter()


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
    session: AsyncSession = Depends(get_session),
):
    # TODO: identify the current user before creating the session
    raise NotImplementedError


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session_history(session_id: uuid.UUID):
    # TODO: identify the current user and verify session ownership
    raise NotImplementedError
