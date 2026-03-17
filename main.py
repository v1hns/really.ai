"""
really.ai — WhatsApp real estate superconnecter
Entry point
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.api.webhook import router as webhook_router
from app.db.engine import create_db
from app.core.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    yield


app = FastAPI(
    title="really.ai",
    description="WhatsApp real estate superconnecter",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "really.ai"}
