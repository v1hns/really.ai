"""
VAPI webhook — receives end-of-call report, updates profile, runs matching
POST /api/vapi/webhook
"""
import json
import logging
from datetime import timezone, datetime
from fastapi import APIRouter, Request
from sqlmodel import Session, select

from app.db.engine import engine
from app.db.models import User, Match, ConsentRequest, ConversationState, UserRole
from app.services import matching
from app.services.twilio_client import send_sms
from app.core.config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/vapi", tags=["vapi"])


@router.post("/webhook")
async def vapi_webhook(request: Request):
    payload = await request.json()
    msg = payload.get("message", {})
    msg_type = msg.get("type", "")

    log.debug(f"VAPI webhook: {msg_type}")

    if msg_type == "end-of-call-report":
        await _handle_end_of_call(msg)

    return {"status": "ok"}


async def _handle_end_of_call(msg: dict):
    call = msg.get("call", {})
    customer = call.get("customer", {})
    phone = customer.get("number", "")

    if not phone:
        log.warning("No phone in VAPI end-of-call report")
        return

    # Extract structured data
    analysis = msg.get("analysis", {})
    structured = analysis.get("structuredData", {})
    summary = analysis.get("summary", "")
    transcript = msg.get("transcript", "")

    log.info(f"VAPI call ended for {phone}. Structured data: {structured}")

    # Save profile + JSON export
    _export_json(phone, structured, summary, transcript)

    with Session(engine) as s:
        user = s.exec(select(User).where(User.phone == phone)).first()
        if not user:
            log.warning(f"No user found for {phone}")
            return

        # Apply structured data to profile
        field_map = {
            "role", "location", "budget_min", "budget_max",
            "property_types", "bedrooms", "timeline", "requirements",
            "listing_address", "listing_price", "listing_description",
        }
        for key, val in structured.items():
            if key in field_map and val is not None:
                if key == "role":
                    try:
                        val = UserRole(val)
                    except ValueError:
                        continue
                setattr(user, key, val)

        if not user.requirements and summary:
            user.requirements = summary

        user.state = ConversationState.ACTIVE
        user.updated_at = datetime.now(timezone.utc)
        s.add(user)
        s.commit()
        s.refresh(user)

        # Run matching
        matches = matching.find_matches(user, s)
        for matched_user, score, reason in matches:
            # Record match
            m = Match(
                initiator_id=user.id,
                target_id=matched_user.id,
                score=score,
                reason=reason,
            )
            s.add(m)
            s.commit()
            s.refresh(m)

            # SMS the existing (matched) user asking for consent
            _send_consent_sms(matched_user, user, m.id, s)

            # New user implicitly consented (they just did the call)
            cr_new = ConsentRequest(match_id=m.id, user_id=user.id, consented=True,
                                    responded_at=datetime.now(timezone.utc))
            s.add(cr_new)
            s.commit()

            log.info(f"Match found: {user.phone} ↔ {matched_user.phone} score={score:.2f}")


def _send_consent_sms(to_user: User, new_user: User, match_id: int, session: Session):
    """SMS the existing matched user asking if they want to connect."""
    name = new_user.name or "Someone"
    role = new_user.role.value if new_user.role else "real estate professional"
    location = new_user.location or "your market"
    summary = new_user.requirements or f"looking in {location}"

    msg = (
        f"Hey {to_user.name or 'there'}! Really found a match for you 🏡\n\n"
        f"{name} is a {role} — {summary}.\n\n"
        f"Reply YES to connect or NO to pass."
    )

    # Track consent request
    cr = ConsentRequest(match_id=match_id, user_id=to_user.id)
    session.add(cr)
    session.commit()

    if settings.TWILIO_ACCOUNT_SID:
        try:
            send_sms(to=to_user.phone, body=msg)
        except Exception as e:
            log.error(f"SMS failed to {to_user.phone}: {e}")
    else:
        log.info(f"[SMS would send to {to_user.phone}]: {msg}")


def _export_json(phone: str, structured: dict, summary: str, transcript: str):
    """Save call data as JSON to /exports/."""
    import os
    os.makedirs("exports", exist_ok=True)
    safe_phone = phone.replace("+", "").replace(" ", "_")
    path = f"exports/{safe_phone}_{int(datetime.now(timezone.utc).timestamp())}.json"
    data = {
        "phone": phone,
        "structured_profile": structured,
        "summary": summary,
        "transcript": transcript,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"Profile exported → {path}")
