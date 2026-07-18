import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from src.agent.session import ConversationSession
from src.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é um assistente financeiro que ajuda usuários a entender sua carteira \
e histórico de transações. Use as ferramentas disponíveis para fundamentar suas respostas em \
dados reais.

Regras:
- Responda no mesmo idioma que o usuário escreve.
- Nunca invente ou estime valores — use sempre as ferramentas para consultar os dados.
- Nunca revele ou mencione dados de outros usuários.
- Quando uma consulta não retornar resultados, informe claramente ao usuário."""


def get_llm() -> BaseChatModel:
    """
    Returns a configured LangChain chat model based on settings.llm_provider.
    Add new providers here to extend support.
    """
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=settings.llm_model, api_key=settings.llm_api_key)

    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=settings.llm_model, api_key=settings.llm_api_key)

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider!r}")


async def chat(
    message: str,
    session: ConversationSession,
    tools: list[BaseTool],
) -> str:
    """Run the tool-calling loop for one user turn, appending messages to `session` in place."""
    llm = get_llm().bind_tools(tools)  # tells the model it may call tools and what they are.
    tool_map = {t.name: t for t in tools}

    session.messages.append(HumanMessage(content=message))

    while True:
        response = await llm.ainvoke(
            [SystemMessage(content=SYSTEM_PROMPT)] + session.messages
        )
        session.messages.append(response)

        if not response.tool_calls:
            return response.content if isinstance(response.content, str) else str(response.content)

        for tool_call in response.tool_calls:
            tool = tool_map.get(tool_call["name"])
            if tool is None:
                result = {"error": f"Unknown tool: {tool_call['name']}"}
            else:
                try:
                    result = await tool.ainvoke(tool_call["args"])
                except Exception as e:
                    logger.warning(f"Tool {tool_call['name']} failed for call {tool_call['id']}: {e}")
                    result = {"error": str(e)}

            session.messages.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )
