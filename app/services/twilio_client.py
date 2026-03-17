"""
Twilio REST client — outbound calls and SMS fallback
"""
from twilio.rest import Client
from app.core.config import settings

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    return _client


def make_call(to: str, webhook_base_url: str, context: str = "") -> str:
    """
    Initiate an outbound call to `to`.
    Returns the Twilio call SID.

    `context` is passed as a query param so the call handler knows
    why Really is calling (e.g. 'match', 'intake').
    """
    import urllib.parse
    params = {"context": context} if context else {}
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""

    call = get_client().calls.create(
        to=to,
        from_=settings.TWILIO_PHONE_NUMBER,
        url=f"{webhook_base_url}/api/calls/incoming{qs}",
        status_callback=f"{webhook_base_url}/api/calls/status",
        status_callback_method="POST",
    )
    return call.sid


def send_sms(to: str, body: str) -> str:
    """Send a plain SMS via Twilio (fallback channel)."""
    msg = get_client().messages.create(
        to=to,
        from_=settings.TWILIO_PHONE_NUMBER,
        body=body,
    )
    return msg.sid
