"""
Call handler — processes one speech turn during a phone call and
returns the next TwiML response to serve to Twilio.

Architecture:
  Twilio call → <Gather input="speech"> → POST /api/calls/respond
              → call_handler.handle_call_turn()
              → returns TwiML XML string
              → Twilio reads it aloud + gathers next turn → loop

State is persisted in the same User/Message DB as WhatsApp, keyed by
phone number, so conversation history is shared across channels.
"""
from datetime import datetime
from sqlmodel import Session, select
from twilio.twiml.voice_response import VoiceResponse, Gather

from app.db.models import User, Message, ConversationState, UserRole
from app.db.engine import engine
from app.services import ai, matching
from app.core.config import settings
from app.core.handler import (
    _get_or_create_user,
    _get_history,
    _save_message,
    _apply_profile_update,
)

import logging
log = logging.getLogger(__name__)

# Twilio voice — neural voices give the most natural feel
VOICE = "Polly.Joanna-Neural"

# Prompt addition telling Claude it's on a phone call
CALL_SYSTEM_EXTRA = (
    "You are on a PHONE CALL — keep each response under 60 words, "
    "speak in plain sentences (no bullet points, asterisks, or markdown), "
    "ask only ONE question per turn, and sound warm and conversational."
)

GREETING_INTAKE = (
    "Hey there, thanks for calling Really — your AI real estate superconnecter. "
    "I'm going to ask you a few quick questions to find you the perfect match. "
    "Are you looking to buy, sell, rent, rent out a property, find clients as an agent, or invest in real estate?"
)

GREETING_MATCH = (
    "Hey, this is Really calling — I just found someone you really should meet in real estate. "
    "Got 90 seconds? I'll tell you about them."
)

GOODBYE = (
    "Great talking with you! I'll send you a follow-up on WhatsApp with everything we covered. "
    "Talk soon!"
)


def _build_call_context(user: User) -> str:
    return (
        f"{CALL_SYSTEM_EXTRA} "
        f"User state: {user.state.value}. "
        f"User role: {user.role.value}. "
        f"Profile so far: location={user.location}, "
        f"budget={user.budget_min}-{user.budget_max}, "
        f"property_types={user.property_types}, "
        f"requirements={user.requirements}."
    )


def _twiml_ask(say_text: str, action: str, timeout: int = 5) -> str:
    """Return TwiML that speaks then listens for a reply."""
    resp = VoiceResponse()
    gather = Gather(
        input="speech",
        action=action,
        method="POST",
        speech_timeout="auto",
        language="en-US",
        enhanced=True,               # Twilio's enhanced STT model
    )
    gather.say(say_text, voice=VOICE)
    resp.append(gather)
    # If user doesn't say anything, redirect back
    resp.redirect(action, method="POST")
    return str(resp)


def _twiml_say_and_hangup(text: str) -> str:
    resp = VoiceResponse()
    resp.say(text, voice=VOICE)
    resp.hangup()
    return str(resp)


def incoming_call_twiml(phone: str, context: str = "", webhook_base: str = "") -> str:
    """
    Called when a call first connects (inbound or outbound).
    Returns TwiML that greets the user and listens for their first response.
    """
    action = f"{webhook_base}/api/calls/respond"

    if context == "match":
        greeting = GREETING_MATCH
    else:
        greeting = GREETING_INTAKE

    return _twiml_ask(greeting, action)


async def handle_call_turn(
    phone: str,
    speech_result: str,
    call_sid: str,
    webhook_base: str,
) -> str:
    """
    Process one speech turn and return the next TwiML.
    """
    action = f"{webhook_base}/api/calls/respond"

    with Session(engine) as session:
        user = _get_or_create_user(phone, session)
        user.last_active = datetime.utcnow()
        session.add(session.merge(user))
        session.commit()
        session.refresh(user)

        # Handle opt-out keywords
        if any(w in speech_result.lower() for w in ["stop", "unsubscribe", "remove me", "opt out"]):
            user.opt_in = False
            session.add(user)
            session.commit()
            return _twiml_say_and_hangup(
                "No problem, I've removed you from Really. Have a great day!"
            )

        history = _get_history(user, session)
        system_extra = _build_call_context(user)

        reply, profile_update = await ai.get_reply(user, history, speech_result, system_extra)

        # Strip any markdown that slipped through (safety net for TTS)
        reply_clean = (
            reply
            .replace("*", "")
            .replace("_", "")
            .replace("#", "")
            .replace("`", "")
        )

        _save_message(user.id, "user", speech_result, session)
        _save_message(user.id, "assistant", reply_clean, session)

        if profile_update:
            _apply_profile_update(user, profile_update, session)
            session.refresh(user)

        # Check if profile just completed — run matching then wrap up call
        if user.state == ConversationState.ACTIVE:
            try:
                matches = matching.find_matches(user, session)
                if matches:
                    matched_user, score, reason = matches[0]
                    match_blurb = await ai.build_intro_message(user, matched_user)
                    match_blurb_clean = match_blurb.replace("*", "").replace("_", "")

                    # Record match
                    from app.db.models import Match
                    m = Match(
                        initiator_id=user.id,
                        target_id=matched_user.id,
                        score=score,
                        reason=reason,
                        introduced=True,
                    )
                    session.add(m)
                    user.state = ConversationState.MATCHED
                    matched_user.state = ConversationState.MATCHED
                    session.add(user)
                    session.add(matched_user)
                    session.commit()

                    # Send WhatsApp follow-ups async (fire-and-forget)
                    _schedule_whatsapp_followups(user, matched_user, match_blurb)

                    closing = (
                        f"{reply_clean} "
                        f"Great news — I already found a match for you! "
                        f"{match_blurb_clean} "
                        f"I'll send you their details on WhatsApp right now. {GOODBYE}"
                    )
                    return _twiml_say_and_hangup(closing)
            except Exception as e:
                log.error(f"Call matching error: {e}")

        # Detect natural end-of-conversation signals
        farewell_keywords = ["bye", "goodbye", "thanks", "that's all", "that is all", "done", "hang up"]
        if any(kw in speech_result.lower() for kw in farewell_keywords):
            _save_message(user.id, "assistant", GOODBYE, session)
            return _twiml_say_and_hangup(GOODBYE)

        return _twiml_ask(reply_clean, action)


def _schedule_whatsapp_followups(user: User, matched_user: User, intro_text: str):
    """Fire-and-forget WhatsApp messages after a call-triggered match."""
    import asyncio
    from app.services import whatsapp

    async def _send():
        try:
            await whatsapp.send_message(
                user.phone,
                f"🏡 *Your call with Really found a match!*\n\n{intro_text}\n\n"
                "Reply YES to share your contact with them.",
            )
            reverse = await ai.build_intro_message(matched_user, user)
            await whatsapp.send_message(
                matched_user.phone,
                f"🏡 *Really found a connection for you!*\n\n{reverse}\n\n"
                "Reply YES to share your contact with them.",
            )
        except Exception as e:
            log.error(f"WhatsApp follow-up failed: {e}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_send())
        else:
            loop.run_until_complete(_send())
    except Exception as e:
        log.error(f"Could not schedule WhatsApp follow-ups: {e}")
