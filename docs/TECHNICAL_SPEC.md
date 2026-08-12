# Especificação Técnica — Carteira Digital

## 1. Stack Tecnológica

| Camada              | Escolha                                    | Justificativa                                        |
|---------------------|--------------------------------------------|------------------------------------------------------|
| Linguagem           | Python 3.11+                               | Tipagem moderna, ecossistema async                   |
| Framework Web       | FastAPI                                    | Async, tipado, docs automáticos, padrão de mercado   |
| ORM                 | SQLAlchemy 2.x (async)                     | Sessões async, controle fino de bloqueios            |
| Banco de Dados      | PostgreSQL 15                              | ACID, bloqueio em nível de linha para saldo          |
| Migrações           | Alembic                                    | Versionamento de schema junto com SQLAlchemy         |
| Autenticação        | python-jose + passlib                      | JWT HS256, hash bcrypt                               |
| HTTP Client         | httpx (async)                              | Chamadas à API do gateway                            |
| Agente de IA        | LangChain (`langchain-core` + adapter)     | Abstração de provider — troque o LLM via config      |
| Validação           | Pydantic v2                                | Schemas de request/response, settings                |
| Testes              | pytest + pytest-asyncio + httpx            | Cliente de teste async                               |
| LLM (padrão)        | `langchain-anthropic` (Claude)             | Adapter padrão; substitua por outro sem mudar código |
| Container           | Docker + Docker Compose                    | Ambiente reproduzível local e em CI                  |

---

## 2. Estrutura do Projeto

```
virtual-wallet/
├── docs/
│   ├── BUSINESS_SPEC.md
│   ├── TECHNICAL_SPEC.md
│   ├── ARCHITECTURE.md
│   └── AUTH_GUIDE.md
│
├── src/
│   ├── wallet/                    — domínio principal
│   │   ├── models.py              — modelos ORM (SQLAlchemy)
│   │   ├── schemas.py             — schemas Pydantic de request/response
│   │   ├── service.py             — lógica de negócio
│   │   ├── repository.py          — queries ao DB (sessões SQLAlchemy)
│   │   └── router.py              — rotas FastAPI
│   │
│   ├── gateway/                   — abstração de gateway de pagamento
│   │   ├── base.py                — interface PaymentGateway (Protocol)
│   │   ├── webhook_handler.py     — verificação de webhook + despacho
│   │   └── stripe_gateway.py      — implementação Stripe
│   │
│   ├── agent/                     — agente de consultas
│   │   ├── tools.py               — definições de ferramentas
│   │   ├── session.py             — gerenciamento de sessão de conversa
│   │   ├── agent.py               — loop LangChain com tool use
│   │   └── router.py              — rotas do agente
│   │
│   ├── auth/                      — autenticação
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── service.py
│   │   └── router.py
│   │
│   ├── database.py                — engine async + factory de sessão
│   ├── config.py                  — Pydantic Settings (env vars)
│   └── main.py                    — factory do app FastAPI + routers
│
├── tests/
│   ├── unit/
│   │   ├── test_wallet_service.py
│   │   └── test_agent_tools.py
│   └── integration/
│       ├── test_wallet_creation.py
│       ├── test_deposit_flow.py
│       ├── test_transactions.py
│       └── test_agent_chat.py
│
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
└── README.md
```

Schema: as tabelas são criadas no startup via SQLAlchemy `create_all` (ver §5 para o DDL de referência).

---

## 3. Variáveis de Ambiente

```bash
# Aplicação
DATABASE_URL=postgresql+asyncpg://wallet:wallet@db:5432/wallet
SECRET_KEY=<hex-aleatório-256-bits>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Gateway — escolha um
GATEWAY_PROVIDER=stripe            # ou mercadopago
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
# MERCADO_PAGO_ACCESS_TOKEN=...

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6
```

---

## 4. Decisões de Design

### 4.1 Atomicidade de Saldo

Use `SELECT ... FOR UPDATE` (bloqueio pessimista) na linha da carteira antes de qualquer
mutação de saldo. Isso garante que requisições concorrentes se serializam naturalmente no
nível do banco de dados.

```python
# repository.py — padrão de exemplo
async def get_wallet_for_update(session: AsyncSession, wallet_id: UUID) -> Wallet:
    result = await session.execute(
        select(Wallet)
        .where(Wallet.id == wallet_id)
        .with_for_update()
    )
    return result.scalar_one()
```

> **Observação:** operações em uma única carteira (depósito, saque) são diretas. Transferências
> entre usuários bloqueiam **duas** linhas de carteira na mesma transação. Considere as
> implicações de ordem de aquisição de locks nesse cenário.

### 4.2 Abstração de Gateway

Todas as interações com o gateway passam pelo protocolo `PaymentGateway`. Isso permite que
testes unitários injetem um `FakeGateway` sem fazer chamadas HTTP reais.

```python
# gateway/base.py
from typing import Protocol
from decimal import Decimal
from dataclasses import dataclass

@dataclass
class PaymentIntent:
    gateway_reference: str
    client_secret: str | None
    status: str

class PaymentGateway(Protocol):
    async def create_deposit_intent(self, amount: Decimal, currency: str, metadata: dict) -> PaymentIntent: ...
    async def create_payout(self, amount: Decimal, destination: dict, metadata: dict) -> PaymentIntent: ...
    def verify_webhook(self, payload: bytes, signature: str) -> dict: ...
```

### 4.3 Agente com LangChain (agnóstico de provider)

O agente usa `langchain-core` para abstrair o provider de LLM. A troca de provider é feita
apenas via variável de ambiente — sem alteração de código:

```python
# agent/agent.py — fluxo conceitual
def get_llm() -> BaseChatModel:
    if settings.llm_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=settings.llm_model, api_key=settings.llm_api_key)
    if settings.llm_provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=settings.llm_model, api_key=settings.llm_api_key)

async def chat(message: str, session: ConversationSession, tools: list[BaseTool]) -> str:
    llm = get_llm().bind_tools(tools)
    session.messages.append(HumanMessage(content=message))

    while True:
        response = await llm.ainvoke([SystemMessage(content=SYSTEM_PROMPT)] + session.messages)
        session.messages.append(response)

        if not response.tool_calls:
            return response.content

        for tool_call in response.tool_calls:
            result = await tool_map[tool_call["name"]].ainvoke(tool_call["args"])
            session.messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))
```

As ferramentas são criadas por `build_tools(repo, user_id)` em `agent/tools.py`, usando o
decorator `@tool` do `langchain-core`. Cada ferramenta é um closure sobre `user_id`, garantindo
que todas as queries fiquem escopadas ao usuário autenticado.

### 4.4 Idempotência de Webhook

O endpoint de webhook usa `gateway_reference` como chave de idempotência. Se uma transação
com a referência informada já existir em estado terminal (`COMPLETED`, `FAILED`), o webhook
é confirmado mas nenhuma mutação de estado ocorre.

---

## 5. Schema do Banco de Dados (DDL de Referência)

```sql
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    hashed_password TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE wallets (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    balance     NUMERIC(18, 2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
    currency    CHAR(3) NOT NULL DEFAULT 'BRL',
    status      TEXT NOT NULL DEFAULT 'ACTIVE',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id)
);

CREATE TABLE transactions (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet_id                   UUID NOT NULL REFERENCES wallets(id),
    type                        TEXT NOT NULL,
    amount                      NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
    balance_before              NUMERIC(18, 2) NOT NULL,
    balance_after               NUMERIC(18, 2) NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'PENDING',
    description                 TEXT,
    counterpart_transaction_id  UUID REFERENCES transactions(id),
    gateway_reference           TEXT UNIQUE,
    metadata                    JSONB,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_transactions_wallet_created ON transactions (wallet_id, created_at DESC);
CREATE INDEX idx_transactions_type           ON transactions (wallet_id, type);
CREATE INDEX idx_transactions_status         ON transactions (wallet_id, status);
```

---

## 6. Estratégia de Testes

| Camada            | Abordagem                                                              |
|-------------------|------------------------------------------------------------------------|
| Domínio / Serviço | Testes unitários com fakes em memória — sem DB, sem gateway, sem HTTP  |
| Repositório       | Testes de integração contra uma instância real de PostgreSQL (Docker)  |
| Gateway           | Testes unitários com `httpx.MockTransport` ou `respx`                  |
| Ferramentas do Agente | Testes unitários verificando queries e escopo de dados por usuário |
| API               | Testes de integração usando `AsyncClient` contra o app FastAPI completo|
| Loop do Agente    | Testes de contrato verificando fluxo tool call → resultado → resposta  |

---

## 7. Docker Compose

```yaml
# docker-compose.yml (referência)
services:
  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    depends_on:
      db:
        condition: service_healthy

  db:
    image: postgres:15
    environment:
      POSTGRES_USER: wallet
      POSTGRES_PASSWORD: wallet
      POSTGRES_DB: wallet
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U wallet"]
      interval: 5s
      retries: 5
```
