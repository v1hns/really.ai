"""
SMS consent handler — Twilio webhook for YES/NO replies
POST /api/consent/sms

Flow:
  Existing user replies YES → check if new user also consented → send email intro
  Existing user replies NO  → close the match
"""
import logging
from datetime import datetime, timezone
from typing import Annotated, Optional
from fastapi import APIRouter, Form
from sqlmodel import Session, select

from app.db.engine import engine
from app.db.models import ConsentRequest, Match, User
from app.services.email import send_introduction
from app.services.twilio_client import send_sms
from app.core.config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/consent", tags=["consent"])


@router.post("/sms")
async def sms_consent(
    From: Annotated[Optional[str], Form()] = None,
    Body: Annotated[Optional[str], Form()] = None,
):
    """Twilio inbound SMS webhook — handles YES/NO consent replies."""
    phone = (From or "").strip()
    reply = (Body or "").strip().upper()

    if not phone:
        return {"status": "ignored"}

    is_yes = reply in {"YES", "Y", "YEP", "YEAH", "YUP", "1", "OK", "SURE", "CONNECT"}
    is_no = reply in {"NO", "N", "NOPE", "PASS", "SKIP", "0", "DECLINE"}

    if not is_yes and not is_no:
        # Unrecognised reply — prompt again
        if settings.TWILIO_ACCOUNT_SID:
            send_sms(phone, "Reply YES to connect or NO to pass.")
        return {"status": "prompted"}

    with Session(engine) as s:
        user = s.exec(select(User).where(User.phone == phone)).first()
        if not user:
            return {"status": "unknown_user"}

        # Find pending consent request for this user
        cr = s.exec(
            select(ConsentRequest)
            .where(ConsentRequest.user_id == user.id, ConsentRequest.consented == None)
            .order_by(ConsentRequest.created_at.desc())
        ).first()

        if not cr:
            return {"status": "no_pending_consent"}

        cr.consented = is_yes
        cr.responded_at = datetime.now(timezone.utc)
        s.add(cr)
        s.commit()

        if not is_yes:
            send_sms(phone, "Got it — no problem. We'll keep looking for better matches for you.")
            return {"status": "declined"}

        # YES — check if other party also consented
        match = s.get(Match, cr.match_id)
        if not match:
            return {"status": "match_not_found"}

        other_user_id = (
            match.target_id if match.initiator_id != user.id else match.initiator_id
        )
        other_cr = s.exec(
            select(ConsentRequest)
            .where(
                ConsentRequest.match_id == cr.match_id,
                ConsentRequest.user_id == other_user_id,
            )
        ).first()

        if not other_cr or other_cr.consented is None:
            # Other party hasn't responded yet — notify them that this user said yes
            other_user = s.get(User, other_user_id)
            if other_user:
                msg = (
                    f"{user.name or 'Your match'} said yes to connecting with you! 🎉\n"
                    f"Would you like to connect too? Reply YES or NO."
                )
                if settings.TWILIO_ACCOUNT_SID:
                    send_sms(other_user.phone, msg)
            send_sms(phone, "You're in! We're waiting on the other party — we'll email both of you once they confirm.")
            return {"status": "waiting_for_other"}

        if other_cr.consented is False:
            send_sms(phone, "The other party passed on this one, but we'll keep looking for matches for you.")
            return {"status": "other_declined"}

        # Both said YES — send email introduction
        this_user = user
        other_user = s.get(User, other_user_id)

        if not other_user:
            return {"status": "other_user_not_found"}

        initiator = s.get(User, match.initiator_id)
        target = s.get(User, match.target_id)

        try:
            email_id = await send_introduction(initiator, target)
            match.introduced = True
            s.add(match)
            s.commit()
            log.info(f"Email intro sent: {email_id} — {initiator.phone} ↔ {target.phone}")

            send_sms(this_user.phone, "Both parties are in! Check your email — we just sent a formal introduction. 🏡")
            send_sms(other_user.phone, "Both parties are in! Check your email — we just sent a formal introduction. 🏡")

        except Exception as e:
            log.error(f"Email intro failed: {e}")
            send_sms(phone, "You both said yes! We'll send the intro email shortly.")

        return {"status": "introduced"}
