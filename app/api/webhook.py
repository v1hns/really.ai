"""
WhatsApp Cloud API webhook endpoints
"""
from fastapi import APIRouter, Query, Request, HTTPException, Response
from app.core.config import settings
from app.core.handler import handle_message, send_welcome
from app.db.models import User, ConversationState
from sqlmodel import Session, select
import logging

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """Meta webhook verification handshake."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        log.info("Webhook verified")
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request):
    """Receive and process incoming WhatsApp messages."""
    payload = await request.json()
    log.debug(f"Webhook payload: {payload}")

    # Import here to avoid circular
    from app.services.whatsapp import parse_incoming

    events = parse_incoming(payload)
    for event in events:
        phone = event["from"]
        text = event["text"]
        button_id = event.get("button_id")

        # Check if this is a new user (no history)
        from app.db.engine import engine
        with Session(engine) as s:
            user = s.exec(select(User).where(User.phone == phone)).first()
            is_new = user is None or user.state == ConversationState.GREETING

        if is_new and not button_id:
            await send_welcome(phone)
        else:
            await handle_message(phone, text, button_id)

    return {"status": "ok"}
