"""
really.ai — Telegram real estate superconnecter
Entry point
"""
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.webhook import router as webhook_router
from app.api.intake import router as intake_router
from app.api.vapi_webhook import router as vapi_router
from app.db.engine import create_db
from app.core.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    # Register Telegram webhook if PUBLIC_BASE_URL is configured
    if settings.PUBLIC_BASE_URL and settings.TELEGRAM_BOT_TOKEN:
        try:
            webhook_url = f"{settings.PUBLIC_BASE_URL}/api/webhook"
            payload = {"url": webhook_url}
            if settings.TELEGRAM_WEBHOOK_SECRET:
                payload["secret_token"] = settings.TELEGRAM_WEBHOOK_SECRET
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook",
                    json=payload,
                )
                r.raise_for_status()
                log.info(f"Telegram webhook registered: {webhook_url}")
        except Exception as e:
            log.warning(f"Failed to register Telegram webhook: {e}")
    yield


app = FastAPI(
    title="really.ai",
    description="Telegram real estate superconnecter",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router, prefix="/api")
app.include_router(intake_router, prefix="/api")
app.include_router(vapi_router, prefix="/api")

# Serve landing page
app.mount("/static", StaticFiles(directory="web"), name="static")

@app.get("/")
async def index():
    return FileResponse("web/index.html")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "really.ai"}
