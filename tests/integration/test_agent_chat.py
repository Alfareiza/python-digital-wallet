"""
Integration tests for the agent chat endpoints.

These tests hit the FastAPI app end to end. The LLM must be stubbed — do NOT
make real calls to Anthropic/OpenAI. Inject a fake chat model (or patch
`src.agent.agent.get_llm`) that returns deterministic tool calls and answers,
so the tool-call → result → answer contract can be asserted without a network.

Covers BUSINESS_SPEC A-01..A-06: scoped tool calls, multi-turn history, and
graceful handling of empty/ambiguous queries.
"""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from src.agent import agent as agent_module


class _ScriptedChatModel(FakeMessagesListChatModel):
    """FakeMessagesListChatModel whose bind_tools is a no-op — responses are pre-scripted with tool_calls."""

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        """Ignore the tool schema binding since the scripted responses already carry any tool_calls."""
        return self


@pytest.fixture
def stub_llm(monkeypatch):
    """Return a factory that patches src.agent.agent.get_llm to cycle through the given AIMessage responses."""

    def _stub(responses: list[AIMessage]) -> _ScriptedChatModel:
        model = _ScriptedChatModel(responses=responses)
        monkeypatch.setattr(agent_module, "get_llm", lambda: model)
        return model

    return _stub


class TestAgentChat:
    async def test_chat_requires_authentication(self, client: AsyncClient):
        """Verify POST /agent/chat rejects requests without a bearer token."""
        resp = await client.post("/agent/chat", json={"message": "Qual é o meu saldo?"})
        assert resp.status_code == 401

    async def test_chat_answers_grounded_in_tool_results(
        self, client: AsyncClient, db_session, make_wallet, register_user, stub_llm
    ):
        """Verify a tool-triggering question runs the real scoped tool and returns the follow-up answer."""
        user = await register_user("agent.grounded@example.com", name="Agent Grounded")

        db_session.add(make_wallet(user_id=user.id, balance=Decimal("250.00")))
        await db_session.commit()

        stub_llm(
            [
                AIMessage(content="", tool_calls=[{"name": "get_wallet_summary", "args": {}, "id": "call_1"}]),
                AIMessage(content="Seu saldo atual é R$ 250.00."),
            ]
        )

        resp = await client.post("/agent/chat", json={"message": "Qual é o meu saldo?"}, headers=user.headers)

        assert resp.status_code == 200
        assert "250.00" in resp.json()["answer"]

    async def test_multi_turn_history_is_preserved(
        self, client: AsyncClient, db_session, make_wallet, register_user, stub_llm
    ):
        """Verify the second turn reuses the session_id and the full message history accumulates across turns."""
        user = await register_user("agent.multiturn@example.com", name="Agent Multiturn")

        db_session.add(make_wallet(user_id=user.id, balance=Decimal("80.00")))
        await db_session.commit()

        stub_llm(
            [
                AIMessage(content="", tool_calls=[{"name": "get_wallet_summary", "args": {}, "id": "call_1"}]),
                AIMessage(content="Seu saldo atual é R$ 80.00."),
                AIMessage(content="Sim, o saldo de R$ 80.00 que mencionei permanece o mesmo."),
            ]
        )

        first = await client.post("/agent/chat", json={"message": "Qual é o meu saldo?"}, headers=user.headers)
        session_id = first.json()["session_id"]

        second = await client.post(
            "/agent/chat", json={"message": "Isso mudou?", "session_id": session_id}, headers=user.headers
        )

        assert second.json()["session_id"] == session_id
        assert second.json()["answer"] == "Sim, o saldo de R$ 80.00 que mencionei permanece o mesmo."

        history = await client.get(f"/agent/sessions/{session_id}", headers=user.headers)
        roles = [message["role"] for message in history.json()["messages"]]
        assert roles == ["human", "ai", "tool", "ai", "human", "ai"]

    async def test_tool_calls_are_scoped_to_the_caller(
        self, client: AsyncClient, db_session, make_wallet, register_user, stub_llm
    ):
        """Verify the agent's tool call for one user never surfaces another user's wallet data."""
        user_a = await register_user("agent.scope.a@example.com", name="Agent Scope A")
        user_b = await register_user("agent.scope.b@example.com", name="Agent Scope B")

        db_session.add(make_wallet(user_id=user_a.id, balance=Decimal("30.00")))
        db_session.add(make_wallet(user_id=user_b.id, balance=Decimal("9999.00")))
        await db_session.commit()

        stub_llm(
            [
                AIMessage(content="", tool_calls=[{"name": "get_wallet_summary", "args": {}, "id": "call_1"}]),
                AIMessage(content="Seu saldo atual é R$ 30.00."),
            ]
        )

        resp = await client.post("/agent/chat", json={"message": "Qual é o meu saldo?"}, headers=user_a.headers)

        assert resp.status_code == 200
        assert "30.00" in resp.json()["answer"]
        assert "9999.00" not in resp.json()["answer"]

    async def test_handles_empty_result_gracefully(self, client: AsyncClient, register_user, stub_llm):
        """Verify a question whose tool call returns no data still completes with a normal 200 answer."""
        user = await register_user("agent.empty@example.com")
        await client.post("/wallet", headers=user.headers)

        stub_llm(
            [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "list_transactions", "args": {"type": "WITHDRAWAL"}, "id": "call_1"}],
                ),
                AIMessage(content="Você não possui nenhuma transação de saque registrada."),
            ]
        )

        resp = await client.post("/agent/chat", json={"message": "Quais foram meus saques?"}, headers=user.headers)

        assert resp.status_code == 200
        assert "não possui" in resp.json()["answer"]


class TestSessionHistory:
    async def test_get_session_returns_conversation_history(self, client: AsyncClient, register_user, stub_llm):
        """Verify GET /agent/sessions/{id} returns the human/ai messages of a session owned by the caller."""
        user = await register_user("agent.session.owner@example.com")
        await client.post("/wallet", headers=user.headers)
        stub_llm([AIMessage(content="Olá! Como posso ajudar?")])

        chat_resp = await client.post("/agent/chat", json={"message": "Oi"}, headers=user.headers)
        session_id = chat_resp.json()["session_id"]

        resp = await client.get(f"/agent/sessions/{session_id}", headers=user.headers)

        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert messages[0] == {"role": "human", "content": "Oi"}
        assert messages[1] == {"role": "ai", "content": "Olá! Como posso ajudar?"}

    async def test_cannot_read_another_users_session(self, client: AsyncClient, register_user, stub_llm):
        """Verify GET /agent/sessions/{id} returns 404 when the session belongs to a different user."""
        owner = await register_user("agent.session.a@example.com")
        intruder = await register_user("agent.session.b@example.com")
        await client.post("/wallet", headers=owner.headers)
        stub_llm([AIMessage(content="Olá!")])

        chat_resp = await client.post("/agent/chat", json={"message": "Oi"}, headers=owner.headers)
        session_id = chat_resp.json()["session_id"]

        resp = await client.get(f"/agent/sessions/{session_id}", headers=intruder.headers)

        assert resp.status_code == 404
