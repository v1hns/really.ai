"""
Intake endpoint — phone number submission → VAPI call
POST /api/intake/submit
"""
from fastapi import APIRouter
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db.engine import engine
from app.db.models import User, ConversationState
from app.services.vapi import start_intake_call
from app.core.config import settings

import logging
log = logging.getLogger(__name__)
router = APIRouter(prefix="/intake", tags=["intake"])


class IntakeSubmission(BaseModel):
    phone: str


@router.post("/submit")
async def submit_intake(body: IntakeSubmission):
    digits = ''.join(c for c in body.phone if c.isdigit())
    if len(digits) == 11 and digits[0] == '1':
        digits = digits[1:]
    phone = f"+1{digits}"

    with Session(engine) as s:
        user = s.exec(select(User).where(User.phone == phone)).first()
        if not user:
            user = User(phone=phone)
        user.state = ConversationState.PROFILE_BUILDING
        s.add(user)
        s.commit()
        s.refresh(user)

    call_id = ""
    if settings.VAPI_API_KEY and settings.VAPI_PHONE_NUMBER_ID:
        try:
            call_id = await start_intake_call(phone=phone)
            with Session(engine) as s:
                user = s.exec(select(User).where(User.phone == phone)).first()
                if user:
                    user.vapi_call_id = call_id
                    s.add(user)
                    s.commit()
            log.info(f"VAPI call started: {call_id} → {phone}")
        except Exception as e:
            log.error(f"VAPI call failed for {phone}: {e}")
            raise
    else:
        log.warning("VAPI not configured — skipping call")

    return {"status": "calling", "call_id": call_id}
