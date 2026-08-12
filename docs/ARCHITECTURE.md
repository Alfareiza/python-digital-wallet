# Arquitetura — Carteira Digital

Visão geral da arquitetura, decisões de design e como validar o sistema localmente.

---

## Diagrama de arquitetura

```
┌─────────────────────────────────────────────────────────────────┐
│                        Cliente HTTP / Usuário                    │
└───────────────────────────────┬─────────────────────────────────┘
                                │ JWT Bearer
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
   /auth (JWT)            /wallet, /transactions    /agent/chat
        │                       │                       │
        │              /webhooks/gateway (HMAC)         │
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                ▼
              ┌─────────────────────────────────────┐
              │           WalletService              │
              │  depósito · saque · transferência    │
              └──────────┬──────────────┬────────────┘
                         │              │
              WalletRepository    Agent + Tools (LangChain)
                         │              │
                         ▼              ▼
                   PostgreSQL      Claude / OpenAI
                         │
              StripeGateway (PaymentIntent, Payout, Webhook)
```

---

## Capacidades

| Área | Status | Onde |
|------|--------|------|
| API sobe com `docker compose up` | ✅ | `Dockerfile`, `docker-compose.yml`, `src/main.py` |
| Autenticação JWT (`/auth/register`, `/auth/token`) | ✅ | `src/auth/` |
| Gestão de carteira (W-01..W-04) | ✅ | `src/wallet/service.py`, `repository.py` |
| Depósito via gateway + webhook idempotente (D-01..D-05) | ✅ | `WalletService.deposit`, `confirm_deposit`, `webhook_handler.py` |
| Saque com reserva de saldo (S-01..S-04) | ✅ | `WalletService.withdraw`, `confirm_payout` |
| Transferência atômica entre usuários (T-01..T-05) | ✅ | `WalletService.transfer` (lock ordenado) |
| Histórico paginado e filtrado (H-01..H-03) | ✅ | `GET /transactions`, `GET /transactions/{id}` |
| Agente LLM com 5 ferramentas (A-01..A-06) | ✅ | `src/agent/tools.py`, `agent.py` |
| Integração Stripe abstraída por protocolo | ✅ | `src/gateway/base.py`, `stripe_gateway.py` |
| Testes unitários e de integração | ✅ | `tests/` (~50 casos) |

### Fora do escopo (conforme BUSINESS_SPEC §10)

| Item | Status |
|------|--------|
| Mercado Pago | Não implementado — Stripe escolhido |
| Dashboard admin / congelar contas | Explicitamente fora do escopo |
| KYC, chargeback, multi-moeda | Fora do escopo |

---

## Integrações externas

| Integração | Implementação | Arquivo principal |
|------------|---------------|-------------------|
| **Stripe — depósitos** | `PaymentIntent` criado via REST; confirmação via webhook `payment_intent.succeeded` | `stripe_gateway.py` |
| **Stripe — saques** | Modo simulado por padrão (`STRIPE_SIMULATE_PAYOUTS=true`); payouts reais opcionais | `stripe_gateway.py`, README |
| **Webhooks HMAC** | Verificação de assinatura Stripe (`t` + `v1`); rejeita payloads inválidos | `StripeGateway.verify_webhook` |
| **Idempotência** | Webhooks em estado terminal (`COMPLETED`/`FAILED`) são no-op | `WalletService.confirm_deposit/payout` |
| **LLM (Anthropic/OpenAI)** | Provider trocável via env (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`) | `src/agent/agent.py` |

**Fluxo de depósito (E2E):**

```
POST /wallet/deposit
  → WalletService cria tx PENDING
  → StripeGateway.create_deposit_intent
  → (cliente paga / teste confirma PaymentIntent)
  → POST /webhooks/gateway (HMAC)
  → confirm_deposit → credita saldo → COMPLETED
```

---

## Modelagem de domínio

| Princípio | Como foi aplicado |
|-----------|-------------------|
| **Separação de camadas** | Router (HTTP) → Service (regras) → Repository (persistência) |
| **Gateway abstrato** | `PaymentGateway` (Protocol) — testes usam `FakeGateway` sem HTTP |
| **Estados explícitos** | `WalletStatus`, `TransactionStatus`, `TransactionType` como enums |
| **Atomicidade** | `SELECT ... FOR UPDATE` antes de mutar saldo |
| **Transferências seguras** | Lock de duas carteiras em ordem ascendente de ID (evita deadlock) |
| **Erros de domínio** | `InsufficientFundsError`, `WalletFrozenError`, etc. — mapeados para HTTP no router |

**Entidades principais:** `User` → `Wallet` (1:1) → `Transaction` (1:N), com `counterpart_transaction_id` para transferências e `gateway_reference` UNIQUE para idempotência.

---

## API REST

| Método | Endpoint | Auth | Descrição |
|--------|----------|------|-----------|
| POST | `/auth/register` | — | Criar conta |
| POST | `/auth/token` | — | Obter JWT |
| GET/POST | `/wallet` | JWT | Obter/criar carteira |
| POST | `/wallet/deposit` | JWT | Iniciar depósito (202) |
| POST | `/wallet/withdraw` | JWT | Iniciar saque (202) |
| POST | `/wallet/transfer` | JWT | Transferência interna (201) |
| GET | `/transactions` | JWT | Listar com filtros e paginação |
| GET | `/transactions/{id}` | JWT | Detalhe de transação |
| POST | `/webhooks/gateway` | HMAC | Eventos Stripe |
| POST | `/agent/chat` | JWT | Pergunta em linguagem natural |
| GET | `/agent/sessions/{id}` | JWT | Histórico da conversa |

Documentação interativa: `http://localhost:8000/docs`

---

## Agente baseado em LLM

| Ferramenta | Função |
|------------|--------|
| `get_wallet_summary` | Saldo, moeda, status |
| `list_transactions` | Lista paginada com filtros |
| `aggregate_transactions` | SUM / AVG / COUNT / MAX / MIN |
| `get_top_transactions` | Top-N maiores/menores |
| `get_transaction_detail` | Detalhe por UUID |

**Garantias:**

- Todas as ferramentas são closures sobre `user_id` (`build_tools(repo, user_id)`)
- Sessões multi-turn em memória (`InMemorySessionStore`)
- Loop LangChain com tool-calling (`agent.py`)
- Testes de integração com LLM stubado (`FakeMessagesListChatModel`) — sem chamadas reais à API

---

## Decisões de design e trade-offs

### Stripe em vez de Mercado Pago

Stripe foi escolhido por documentação madura, suporte a webhooks com HMAC e facilidade de mock nos testes (`respx`). Mercado Pago ficaria atrás do mesmo protocolo `PaymentGateway`.

### Pessimistic locking (`SELECT FOR UPDATE`)

Preferido a concorrência otimista porque:

- Operações financeiras exigem consistência forte
- O volume esperado no estágio atual não justifica a complexidade de retry otimista
- O padrão está documentado na TECHNICAL_SPEC §4.1

### Saques simulados por padrão

Payouts reais da Stripe pagam para a conta bancária da **plataforma**, não para PIX/conta do usuário final (isso exigiria Stripe Connect). Para desenvolvimento e testes:

1. `POST /wallet/withdraw` → debita saldo, tx `PENDING`, ref `po_sim_<id>`
2. `POST /confirm-payout/{ref}` → marca `COMPLETED`

Com `STRIPE_SIMULATE_PAYOUTS=false`, o fluxo usa a Payout API real + webhooks `payout.paid` / `payout.failed`.

### Schema via `create_all` (sem Alembic em runtime)

As tabelas são criadas no startup. Alembic está nas dependências para evolução futura; o DDL de referência está na TECHNICAL_SPEC §5.

### Sessões do agente em memória

Adequado para desenvolvimento e demos. Em produção, persistir em Redis ou PostgreSQL.

### Duplicata de `gateway_reference`

A constraint `UNIQUE` no banco impede duplicatas, mas um segundo depósito com a mesma referência hoje propaga `IntegrityError` em vez de HTTP 409 — documentado em `tests/integration/test_deposit_flow.py`.

---

## Como validar localmente

### 1. Subir o ambiente

```bash
cp .env.example .env   # preencher STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, ANTHROPIC_API_KEY
docker compose up --build
```

### 2. Rodar todos os testes

```bash
docker compose exec api pytest -q
```

### 3. Smoke test manual (opcional)

```bash
# Registrar e obter token
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","name":"Developer","password":"secret123"}'

TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -d "username=dev@example.com&password=secret123" | jq -r .access_token)

# Criar carteira
curl -s http://localhost:8000/wallet -H "Authorization: Bearer $TOKEN"

# Depósito (requer chave Stripe de teste válida)
curl -s -X POST http://localhost:8000/wallet/deposit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount":"50.00"}'

# Agente (requer ANTHROPIC_API_KEY)
curl -s -X POST http://localhost:8000/agent/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"Qual é o meu saldo?"}'
```

---

## Cobertura de testes

| Arquivo | Casos | O que valida |
|---------|-------|--------------|
| `tests/unit/test_wallet_service.py` | 13 | Depósito, saque, transferência, criação de carteira — **sem DB, sem HTTP** |
| `tests/unit/test_agent_tools.py` | 14 | Escopo por usuário, filtros, agregações — **sem DB, sem LLM** |
| `tests/integration/test_wallet_creation.py` | 5 | GET/POST `/wallet`, idempotência, auth |
| `tests/integration/test_deposit_flow.py` | 4 | Depósito + webhook, idempotência, assinatura inválida |
| `tests/integration/test_transactions.py` | 10 | Filtros, paginação, escopo por usuário |
| `tests/integration/test_agent_chat.py` | 7 | Tool use, multi-turn, escopo, sessões |
| **Total** | **~50** | |

---

## Mapa de módulos

| Módulo | Arquivo | Responsabilidade |
|--------|---------|------------------|
| Domínio | `src/wallet/service.py` | Regras de negócio |
| Persistência | `src/wallet/repository.py` | Queries, locks, agregações |
| HTTP | `src/wallet/router.py` | Endpoints REST da carteira |
| Gateway | `src/gateway/stripe_gateway.py` | Integração Stripe |
| Webhook | `src/gateway/webhook_handler.py` | Despacho de eventos |
| Agente | `src/agent/tools.py` | 5 ferramentas LangChain |
| Agente | `src/agent/agent.py` | Loop tool-calling |
| Agente | `src/agent/router.py` | `/agent/chat`, sessões |
| Auth | `src/auth/router.py` | Register + login JWT |
| Infra | `src/database.py`, `config.py`, `main.py` | Engine, settings, app factory |

---

## Variáveis de ambiente relevantes

| Variável | Uso |
|----------|-----|
| `DATABASE_URL` | PostgreSQL async (`asyncpg`) |
| `SECRET_KEY` | JWT HS256 |
| `GATEWAY_PROVIDER` | `stripe` (único implementado) |
| `STRIPE_SECRET_KEY` | API Stripe |
| `STRIPE_WEBHOOK_SECRET` | Validação HMAC de webhooks |
| `STRIPE_SIMULATE_PAYOUTS` | `true` (padrão) — saques simulados |
| `LLM_PROVIDER` | `anthropic` ou `openai` |
| `LLM_MODEL` | Ex.: `claude-sonnet-4-6` |
| `LLM_API_KEY` | Chave do provider escolhido |

---

## Observabilidade

Logs estruturados (`logging.info`) em:

- Mudanças de estado de transação via webhook (`WalletService.confirm_deposit`)
- Processamento de webhooks (`webhook_handler.py`)
- Requisições de carteira e agente (`wallet/router.py`, `agent/router.py`)

---

## Referências

- [BUSINESS_SPEC.md](BUSINESS_SPEC.md) — requisitos funcionais
- [TECHNICAL_SPEC.md](TECHNICAL_SPEC.md) — stack e padrões
- [AUTH_GUIDE.md](AUTH_GUIDE.md) — guia de autenticação
