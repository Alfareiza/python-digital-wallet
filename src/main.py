from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.auth.router import router as auth_router
from src.database import engine, init_db
from src.gateway.webhook_handler import router as webhook_router
from src.wallet.router import router as wallet_router
from src.agent.router import router as agent_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Digital Wallet API",
        version="0.1.0",
        description="Digital Wallet with payment gateway integration and AI insights agent.",
        lifespan=lifespan,
    )

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(wallet_router, tags=["wallet"])
    app.include_router(webhook_router, tags=["webhooks"])
    app.include_router(agent_router, prefix="/agent", tags=["agent"])

    return app


app = create_app()
