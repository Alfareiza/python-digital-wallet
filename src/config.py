from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str = "postgresql+asyncpg://wallet:wallet@db:5432/wallet_test"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Payment gateway
    gateway_provider: str = "stripe"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # Skip real Stripe Payout API calls in dev/test (BRL payouts need a funded BR account).
    stripe_simulate_payouts: bool = True
    mercado_pago_access_token: str = ""

    # LLM — provider-agnostic
    llm_provider: str = "anthropic"   # anthropic | openai
    llm_model: str = "claude-sonnet-4-6"
    llm_api_key: str = ""


settings = Settings()
