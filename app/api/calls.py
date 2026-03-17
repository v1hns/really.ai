"""
Twilio voice call webhook endpoints

Endpoints:
  GET/POST /api/calls/incoming  — call connects (inbound or outbound-initiated)
  POST     /api/calls/respond   — each speech turn
  POST     /api/calls/status    — call status callbacks (optional logging)
  POST     /api/calls/trigger   — internal: trigger an outbound call
"""
from fastapi import APIRouter, Form, Request, Response, Body
from typing import Annotated, Optional
import logging

from app.core.call_handler import incoming_call_twiml, handle_call_turn
from app.core.config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/calls", tags=["calls"])

TWIML_CONTENT_TYPE = "application/xml"


def _base_url(request: Request) -> str:
    """Reconstruct the public base URL from the request (works behind ngrok/proxy)."""
    fwd_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    fwd_host = request.headers.get("x-forwarded-host", request.url.netloc)
    base = settings.PUBLIC_BASE_URL or f"{fwd_proto}://{fwd_host}"
    return base.rstrip("/")


@router.api_route("/incoming", methods=["GET", "POST"])
async def call_incoming(
    request: Request,
    From: Annotated[Optional[str], Form()] = None,
    To: Annotated[Optional[str], Form()] = None,
    CallSid: Annotated[Optional[str], Form()] = None,
    context: Optional[str] = None,  # query param set by make_call()
):
    """Called by Twilio when a call first connects."""
    # For outbound calls Twilio sends To as the user's number; inbound sends From
    phone = From or To or "unknown"
    log.info(f"Call connected: {phone} sid={CallSid} context={context}")

    twiml = incoming_call_twiml(
        phone=phone,
        context=context or "",
        webhook_base=_base_url(request),
    )
    return Response(content=twiml, media_type=TWIML_CONTENT_TYPE)


@router.post("/respond")
async def call_respond(
    request: Request,
    From: Annotated[Optional[str], Form()] = None,
    To: Annotated[Optional[str], Form()] = None,
    CallSid: Annotated[Optional[str], Form()] = None,
    SpeechResult: Annotated[Optional[str], Form()] = None,
    Confidence: Annotated[Optional[str], Form()] = None,
):
    """Called by Twilio after each <Gather> speech recognition turn."""
    phone = From or To or "unknown"
    speech = SpeechResult or ""

    log.info(f"Call turn [{CallSid}] {phone!r}: {speech!r} (confidence={Confidence})")

    if not speech.strip():
        # Nothing heard — prompt again
        from app.core.call_handler import _twiml_ask
        twiml = _twiml_ask(
            "Sorry, I didn't catch that — could you say that again?",
            action=f"{_base_url(request)}/api/calls/respond",
        )
        return Response(content=twiml, media_type=TWIML_CONTENT_TYPE)

    twiml = await handle_call_turn(
        phone=phone,
        speech_result=speech,
        call_sid=CallSid or "",
        webhook_base=_base_url(request),
    )
    return Response(content=twiml, media_type=TWIML_CONTENT_TYPE)


@router.post("/status")
async def call_status(
    CallSid: Annotated[Optional[str], Form()] = None,
    CallStatus: Annotated[Optional[str], Form()] = None,
    From: Annotated[Optional[str], Form()] = None,
    To: Annotated[Optional[str], Form()] = None,
):
    """Twilio status callback — logs call lifecycle events."""
    log.info(f"Call status [{CallSid}] {From}->{To}: {CallStatus}")
    return {"status": "ok"}


@router.post("/trigger")
async def trigger_call(
    request: Request,
    phone: str = Body(..., embed=True),
    context: str = Body("intake", embed=True),
):
    """
    Internal endpoint to initiate an outbound call.
    POST /api/calls/trigger  {"phone": "+14155551234", "context": "match"}
    """
    if not settings.TWILIO_ACCOUNT_SID:
        return {"error": "Twilio not configured"}

    from app.services.twilio_client import make_call
    sid = make_call(
        to=phone,
        webhook_base_url=_base_url(request),
        context=context,
    )
    log.info(f"Outbound call triggered to {phone} sid={sid}")
    return {"call_sid": sid, "to": phone, "context": context}
