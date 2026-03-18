"""
Core message handler — orchestrates the full conversation loop
"""
from datetime import datetime
from sqlmodel import Session, select

from app.db.models import User, Message, Match, ConversationState, UserRole
from app.db.engine import engine
from app.services import whatsapp, ai, matching
from app.core.config import settings

import logging
log = logging.getLogger(__name__)


# ─── helpers ────────────────────────────────────────────────────────────────

def _get_or_create_user(phone: str, session: Session) -> User:
    user = session.exec(select(User).where(User.phone == phone)).first()
    if not user:
        user = User(phone=phone)
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def _get_history(user: User, session: Session) -> list[Message]:
    return session.exec(
        select(Message).where(Message.user_id == user.id).order_by(Message.created_at)
    ).all()


def _save_message(user_id: int, role: str, content: str, session: Session):
    msg = Message(user_id=user_id, role=role, content=content)
    session.add(msg)
    session.commit()


def _apply_profile_update(user: User, update: dict, session: Session):
    """Apply AI-extracted profile fields to the User model."""
    field_map = {
        "name", "role", "location", "budget_min", "budget_max",
        "property_types", "bedrooms", "requirements", "timeline",
        "listing_address", "listing_price", "listing_description",
    }
    changed = False
    for key, val in update.items():
        if key in field_map and val is not None:
            if key == "role":
                try:
                    val = UserRole(val)
                except ValueError:
                    continue
            setattr(user, key, val)
            changed = True

    if changed:
        user.updated_at = datetime.now(datetime.UTC)
        # Advance state if profile is building
        if user.state == ConversationState.GREETING:
            user.state = ConversationState.ROLE_SELECTION
        if update.get("role") and user.state == ConversationState.ROLE_SELECTION:
            user.state = ConversationState.PROFILE_BUILDING
        if update.get("profile_complete") and user.state == ConversationState.PROFILE_BUILDING:
            user.state = ConversationState.ACTIVE
        session.add(user)
        session.commit()
        session.refresh(user)


async def _run_matching(user: User, session: Session):
    """Attempt matching and send introduction messages (+ optional call) if matches found."""
    matches = matching.find_matches(user, session)
    for matched_user, score, reason in matches:
        # Record match
        m = Match(initiator_id=user.id, target_id=matched_user.id, score=score, reason=reason)
        session.add(m)

        # Send intro to user via WhatsApp
        intro_to_user = await ai.build_intro_message(user, matched_user)
        await whatsapp.send_message(
            user.phone,
            f"🏡 *Great news — I found someone you should meet!*\n\n{intro_to_user}\n\n"
            f"They've been notified about you too. Reply here if you'd like me to share your contact with them.",
        )

        # Send intro to matched_user via WhatsApp
        intro_to_match = await ai.build_intro_message(matched_user, user)
        await whatsapp.send_message(
            matched_user.phone,
            f"🏡 *I found a great connection for you!*\n\n{intro_to_match}\n\n"
            f"Reply here if you'd like me to share your contact with them.",
        )

        m.introduced = True
        session.add(m)

        # Update both users' states
        user.state = ConversationState.MATCHED
        matched_user.state = ConversationState.MATCHED
        session.add(user)
        session.add(matched_user)

        # Optionally call both parties if Twilio is configured
        if settings.TWILIO_ACCOUNT_SID and settings.PUBLIC_BASE_URL:
            _trigger_match_calls(user.phone, matched_user.phone)

    session.commit()


def _trigger_match_calls(phone_a: str, phone_b: str):
    """Fire outbound calls to both matched parties (non-blocking)."""
    import asyncio
    from app.services.twilio_client import make_call

    def _call(phone: str):
        try:
            make_call(
                to=phone,
                webhook_base_url=settings.PUBLIC_BASE_URL,
                context="match",
            )
            log.info(f"Outbound match call triggered to {phone}")
        except Exception as e:
            log.error(f"Outbound call failed to {phone}: {e}")

    # Run in a thread so we don't block the async handler
    import threading
    threading.Thread(target=_call, args=(phone_a,), daemon=True).start()
    threading.Thread(target=_call, args=(phone_b,), daemon=True).start()


# ─── main handler ────────────────────────────────────────────────────────────

async def handle_message(phone: str, text: str, button_id: str | None = None):
    """Process one incoming WhatsApp message and send a reply."""
    with Session(engine) as session:
        user = _get_or_create_user(phone, session)
        user.last_active = datetime.now(datetime.UTC)
        session.add(user)
        session.commit()
        session.refresh(user)

        # Opt-out handling
        if text.strip().upper() in {"STOP", "UNSUBSCRIBE", "OPTOUT", "OPT OUT", "QUIT"}:
            user.opt_in = False
            session.add(user)
            session.commit()
            await whatsapp.send_message(
                phone,
                "You've been unsubscribed from Really. Reply START anytime to opt back in.",
            )
            return

        # Opt-back-in
        if not user.opt_in and text.strip().upper() in {"START", "YES"}:
            user.opt_in = True
            session.add(user)
            session.commit()

        if not user.opt_in:
            return

        # Use button_id as text if available (more reliable)
        effective_text = button_id or text

        # Grab history
        history = _get_history(user, session)

        # Build system context with user state
        system_extra = (
            f"User state: {user.state.value}. "
            f"User role: {user.role.value}. "
            f"Profile so far: location={user.location}, budget={user.budget_min}-{user.budget_max}, "
            f"property_types={user.property_types}, requirements={user.requirements}."
        )

        # Get AI reply
        reply, profile_update = await ai.get_reply(user, history, effective_text, system_extra)

        # Save conversation turn
        _save_message(user.id, "user", effective_text, session)
        _save_message(user.id, "assistant", reply, session)

        # Apply profile updates
        if profile_update:
            _apply_profile_update(user, profile_update, session)
            session.refresh(user)

        # Send reply — voice note if VOICE_REPLIES is enabled
        if settings.VOICE_REPLIES and settings.OPENAI_API_KEY:
            try:
                from app.services.voice import send_voice_reply
                await send_voice_reply(phone, reply)
            except Exception as e:
                log.warning(f"TTS failed, falling back to text: {e}")
                await whatsapp.send_message(phone, reply)
        else:
            await whatsapp.send_message(phone, reply)

        # Attempt matching when profile becomes active
        if user.state == ConversationState.ACTIVE:
            try:
                await _run_matching(user, session)
            except Exception as e:
                log.error(f"Matching error for {phone}: {e}")


async def send_welcome(phone: str):
    """Send initial greeting to a new user."""
    await whatsapp.send_list(
        to=phone,
        header="👋 Welcome to Really",
        body="I'm Really — your AI real estate superconnecter. I'll match you with the right buyers, sellers, renters, landlords, agents, or investors in your market.\n\nWhat best describes you right now?",
        button_label="I'm looking to...",
        sections=[
            {
                "title": "Real Estate Goals",
                "rows": [
                    {"id": "buyer", "title": "🏠 Buy a property", "description": "Looking to purchase a home or investment"},
                    {"id": "seller", "title": "💰 Sell a property", "description": "Have a property to sell"},
                    {"id": "renter", "title": "🔑 Rent a place", "description": "Looking for a rental"},
                    {"id": "landlord", "title": "🏢 Rent out my property", "description": "Have a rental unit available"},
                    {"id": "agent", "title": "🤝 I'm an agent", "description": "Connect me with clients"},
                    {"id": "investor", "title": "📈 Invest in real estate", "description": "Looking for investment opportunities"},
                ],
            }
        ],
    )
