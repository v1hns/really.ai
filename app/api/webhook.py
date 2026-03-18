"""
Telegram Bot API webhook endpoint
"""
from fastapi import APIRouter, Request, HTTPException
from app.core.config import settings
from app.core.handler import handle_message, send_welcome
from app.db.models import User, ConversationState
from sqlmodel import Session, select
import logging

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook")
async def receive_webhook(request: Request):
    """Receive and process incoming Telegram updates."""
    # Verify secret token if configured
    if settings.TELEGRAM_WEBHOOK_SECRET:
        token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if token != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid secret token")

    payload = await request.json()
    log.debug(f"Webhook payload: {payload}")

    from app.services.telegram import parse_incoming, answer_callback_query

    events = parse_incoming(payload)
    for event in events:
        chat_id = event["from"]
        text = event["text"]
        button_id = event.get("button_id")
        media_id = event.get("media_id")
        callback_query_id = event.get("callback_query_id")

        # Acknowledge callback query immediately to dismiss spinner
        if callback_query_id:
            try:
                await answer_callback_query(callback_query_id)
            except Exception as e:
                log.warning(f"answerCallbackQuery failed: {e}")

        # Transcribe voice messages before processing
        if event["type"] == "audio" and media_id:
            try:
                from app.services.voice import transcribe_telegram_audio
                text = await transcribe_telegram_audio(media_id)
                log.info(f"Transcribed voice from {chat_id}: {text!r}")
            except Exception as e:
                log.error(f"Transcription failed for {chat_id}: {e}")
                await handle_message(
                    chat_id,
                    "Sorry, I couldn't understand that voice message. Could you type it out?",
                )
                continue

        # Check if this is a new user (no history)
        from app.db.engine import engine
        with Session(engine) as s:
            user = s.exec(select(User).where(User.chat_id == chat_id)).first()
            is_new = user is None or user.state == ConversationState.GREETING

        if is_new and not button_id:
            await send_welcome(chat_id)
        else:
            await handle_message(chat_id, text, button_id)

    return {"status": "ok"}
