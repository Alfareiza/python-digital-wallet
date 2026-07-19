# Wallet Interview Challenge

Projeto técnico de entrevista. Construa uma **Carteira Digital** em Python com:

- API REST (FastAPI + PostgreSQL)
- Integração com gateway de pagamento (Stripe ou Mercado Pago)
- Agente de IA para consultas em linguagem natural (Anthropic Claude com tool use)

---

## Leia antes de começar


| Documento                                        | Conteúdo                                                                            |
| ------------------------------------------------ | ----------------------------------------------------------------------------------- |
| [docs/BUSINESS_SPEC.md](docs/BUSINESS_SPEC.md)   | O que construir — regras de domínio, requisitos funcionais, especificação do agente |
| [docs/TECHNICAL_SPEC.md](docs/TECHNICAL_SPEC.md) | Stack sugerida, estrutura de projeto, padrões de design                             |
| [docs/SUBMISSION.md](docs/SUBMISSION.md)         | **Entrega do candidato** — checklist, arquitetura, decisões de design e guia para revisores |


---



## Como começar

```bash
cp .env.example .env        # preencha suas chaves de API
docker compose up --build   # sobe a API + PostgreSQL
```

A API estará disponível em `http://localhost:8000`.  
Documentação interativa em `http://localhost:8000/docs`.

As tabelas são criadas automaticamente no startup da API (via `create_all`); não é necessário rodar migrações.

### Testando saques localmente

Por padrão, `STRIPE_SIMULATE_PAYOUTS=true` no `.env`. Nesse modo, a API **não** chama a Stripe
Payout API (que exige saldo real na conta da plataforma e não roteia PIX/conta bancária do
usuário). O fluxo espelha o depósito:

1. `POST /wallet/withdraw` — debita o saldo e retorna uma transação `PENDING` com `gateway_reference`
   (ex.: `po_sim_<transaction_id>`).
2. `POST /confirm-payout/{gateway_reference}` — marca o saque como `COMPLETED`.

Exemplo (PIX):

```bash
# 1. Iniciar saque
curl -X POST http://localhost:8000/wallet/withdraw \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount": 10, "destination": {"type": "pix", "key": "user@example.com"}, "description": "teste"}'

# 2. Confirmar payout simulado (use o gateway_reference da resposta)
curl -X POST "http://localhost:8000/confirm-payout/po_sim_<transaction_id>" \
  -H "Authorization: Bearer $TOKEN"
```

Para usar payouts reais da Stripe em produção, defina `STRIPE_SIMULATE_PAYOUTS=false` e configure
webhooks para `payout.paid` / `payout.failed`.

---



## Como rodar os testes

Os testes só rodam dentro do container `api` — não é necessário Python/pytest na máquina host. Com a API e o
PostgreSQL já em execução (`docker compose up`):

```bash
docker compose exec api pytest
```

A cada sessão de testes, o `tests/conftest.py` recria do zero um banco `wallet_test` descartável na mesma
instância do serviço `db` (via `settings.test_database_url`), isolado do banco `wallet` usado em desenvolvimento.

---



## O que já está aqui

O repositório inclui:

- `src/` — modelos, schemas e rotas; a **lógica de negócio foi implementada** (service, repository, gateway, agente).
- `tests/` — 50 testes (unitários + integração) cobrindo domínio, gateway, API e agente.
- `pyproject.toml`, `Dockerfile`, `docker-compose.yml` — prontos para uso.

---



## Entregáveis

A entrega completa — checklist, diagrama de arquitetura, decisões de design e guia para revisores — está em **[docs/SUBMISSION.md](docs/SUBMISSION.md)**.

Resumo:

1. **Implementação funcional** que sobe com `docker compose up`
2. **Testes** — unitários para a lógica de domínio (sem DB) e integração ponta a ponta (`docker compose exec api pytest`)
3. **Documentação de decisões** — gateway escolhido, arquitetura, trade-offs e mapeamento aos critérios de avaliação

---



## Prazo estimado

4–8 horas. Priorize correção e clareza em vez de completude. Uma implementação parcial bem projetada vale mais do que uma implementação completa e apressada.

---



## Restrições

- Python 3.11+
- Deve rodar via Docker — sem dependências no host
- Use LangChain para o agente — o provider de LLM deve ser trocável via configuração
- Sem frontend — apenas a API

