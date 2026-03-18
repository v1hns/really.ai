"""
VAPI webhook — handles end-of-call reports for all call types:
  intake   → save profile, run matching, call matched party for consent
  consent  → if yes, call both parties with intro; if no, log and move on
  intro    → no-op (just logging)
"""
import json
import logging
from datetime import timezone, datetime
from fastapi import APIRouter, Request
from sqlmodel import Session, select

from app.db.engine import engine
from app.db.models import User, Match, ConsentRequest, ConversationState, UserRole
from app.services import matching

log = logging.getLogger(__name__)
router = APIRouter(prefix="/vapi", tags=["vapi"])


@router.post("/webhook")
async def vapi_webhook(request: Request):
    payload = await request.json()
    msg = payload.get("message", {})
    if msg.get("type") == "end-of-call-report":
        call_type = (msg.get("call", {}).get("metadata") or {}).get("call_type", "intake")
        if call_type == "intake":
            await _handle_intake(msg)
        elif call_type == "consent":
            await _handle_consent(msg)
    return {"status": "ok"}


# ─── intake ──────────────────────────────────────────────────────────────────

async def _handle_intake(msg: dict):
    phone = msg.get("call", {}).get("customer", {}).get("number", "")
    if not phone:
        return

    analysis = msg.get("analysis", {})
    structured = analysis.get("structuredData", {})
    summary = analysis.get("summary", "")
    transcript = msg.get("transcript", "")

    _export_json(phone, structured, summary, transcript)

    with Session(engine) as s:
        user = s.exec(select(User).where(User.phone == phone)).first()
        if not user:
            log.warning(f"No user for {phone}")
            return

        _apply_structured(user, structured, summary)
        user.state = ConversationState.ACTIVE
        user.updated_at = datetime.now(timezone.utc)
        s.add(user)
        s.commit()
        s.refresh(user)

        matches = matching.find_matches(user, s)
        for matched_user, score, reason in matches:
            m = Match(initiator_id=user.id, target_id=matched_user.id, score=score, reason=reason)
            s.add(m)
            s.commit()
            s.refresh(m)

            # New user implicitly consented by going through intake
            s.add(ConsentRequest(match_id=m.id, user_id=user.id, consented=True,
                                 responded_at=datetime.now(timezone.utc)))
            # Pending consent for matched user
            s.add(ConsentRequest(match_id=m.id, user_id=matched_user.id))
            s.commit()

            # VAPI calls matched party to ask consent
            await _call_for_consent(matched_user, user, m.id)
            log.info(f"Match: {user.phone} ↔ {matched_user.phone} score={score:.2f}")


# ─── consent ─────────────────────────────────────────────────────────────────

async def _handle_consent(msg: dict):
    metadata = msg.get("call", {}).get("metadata") or {}
    phone = msg.get("call", {}).get("customer", {}).get("number", "")
    match_id = int(metadata.get("match_id", 0))
    consented = (msg.get("analysis", {}).get("structuredData") or {}).get("consented", False)

    if not phone or not match_id:
        return

    with Session(engine) as s:
        user = s.exec(select(User).where(User.phone == phone)).first()
        if not user:
            return

        cr = s.exec(
            select(ConsentRequest).where(
                ConsentRequest.match_id == match_id,
                ConsentRequest.user_id == user.id,
            )
        ).first()
        if not cr:
            return

        cr.consented = consented
        cr.responded_at = datetime.now(timezone.utc)
        s.add(cr)
        s.commit()

        if not consented:
            log.info(f"{phone} declined match {match_id}")
            return

        # Check if both consented
        match = s.get(Match, match_id)
        if not match:
            return

        other_id = match.target_id if match.initiator_id != user.id else match.initiator_id
        other_cr = s.exec(
            select(ConsentRequest).where(
                ConsentRequest.match_id == match_id,
                ConsentRequest.user_id == other_id,
            )
        ).first()

        if not other_cr or not other_cr.consented:
            log.info(f"Waiting on other party for match {match_id}")
            return

        # Both consented — call both with each other's number
        other_user = s.get(User, other_id)
        if not other_user:
            return

        match.introduced = True
        s.add(match)
        s.commit()

        await _call_intro(user, other_user)
        await _call_intro(other_user, user)
        log.info(f"Intro calls triggered: {user.phone} ↔ {other_user.phone}")


# ─── helpers ─────────────────────────────────────────────────────────────────

async def _call_for_consent(to_user: User, new_user: User, match_id: int):
    from app.services.vapi import start_consent_call
    from app.core.config import settings
    if not settings.VAPI_API_KEY:
        log.info(f"[VAPI not configured] Would call {to_user.phone} for consent on match {match_id}")
        return
    try:
        await start_consent_call(
            phone=to_user.phone,
            name=to_user.name or "there",
            match_name=new_user.name or "",
            match_role=new_user.role.value if new_user.role else "professional",
            match_location=new_user.location or "your market",
            match_summary=new_user.requirements or f"looking in {new_user.location or 'your market'}",
            match_id=match_id,
        )
    except Exception as e:
        log.error(f"Consent call failed to {to_user.phone}: {e}")


async def _call_intro(user: User, other: User):
    from app.services.vapi import start_intro_call
    from app.core.config import settings
    if not settings.VAPI_API_KEY:
        log.info(f"[VAPI not configured] Would call {user.phone} with intro to {other.phone}")
        return
    try:
        await start_intro_call(
            phone=user.phone,
            name=user.name or "there",
            other_name=other.name or "your match",
            other_phone=other.phone,
        )
    except Exception as e:
        log.error(f"Intro call failed to {user.phone}: {e}")


def _apply_structured(user: User, structured: dict, summary: str):
    field_map = {
        "role", "location", "budget_min", "budget_max", "property_types",
        "bedrooms", "timeline", "requirements", "listing_address",
        "listing_price", "listing_description",
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


def _export_json(phone: str, structured: dict, summary: str, transcript: str):
    import os
    os.makedirs("exports", exist_ok=True)
    safe = phone.replace("+", "").replace(" ", "_")
    path = f"exports/{safe}_{int(datetime.now(timezone.utc).timestamp())}.json"
    with open(path, "w") as f:
        json.dump({
            "phone": phone,
            "structured_profile": structured,
            "summary": summary,
            "transcript": transcript,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }, f, indent=2)
    log.info(f"Profile exported → {path}")
