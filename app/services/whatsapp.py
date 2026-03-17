"""
WhatsApp Cloud API client
https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import httpx
from app.core.config import settings

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


async def send_message(to: str, text: str) -> dict:
    """Send a plain text WhatsApp message."""
    url = f"{GRAPH_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text, "preview_url": False},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()


async def send_buttons(to: str, body: str, buttons: list[dict]) -> dict:
    """Send interactive button message (max 3 buttons).

    buttons = [{"id": "buyer", "title": "Buyer"}]
    """
    url = f"{GRAPH_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                    for b in buttons[:3]
                ]
            },
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()


async def send_list(to: str, header: str, body: str, button_label: str, sections: list[dict]) -> dict:
    """Send an interactive list message.

    sections = [{"title": "I'm looking to...", "rows": [{"id": "buyer", "title": "Buy", "description": "..."}]}]
    """
    url = f"{GRAPH_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header},
            "body": {"text": body},
            "action": {
                "button": button_label,
                "sections": sections,
            },
        },
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()


async def send_audio(to: str, media_id: str) -> dict:
    """Send a pre-uploaded audio file as a WhatsApp voice note."""
    url = f"{GRAPH_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"id": media_id},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()


def parse_incoming(payload: dict) -> list[dict]:
    """Extract message events from a WhatsApp webhook payload.

    Returns list of dicts:
      {
        "from": phone,
        "type": "text" | "interactive" | "audio",
        "text": str,
        "button_id": str | None,
        "media_id": str | None,   # set for audio messages
      }
    """
    events = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                phone = msg.get("from", "")
                msg_type = msg.get("type", "")

                if msg_type == "text":
                    events.append({
                        "from": phone,
                        "type": "text",
                        "text": msg["text"]["body"],
                        "button_id": None,
                        "media_id": None,
                    })
                elif msg_type in ("audio", "voice"):
                    audio = msg.get("audio") or msg.get("voice") or {}
                    events.append({
                        "from": phone,
                        "type": "audio",
                        "text": "",          # filled in after transcription
                        "button_id": None,
                        "media_id": audio.get("id"),
                    })
                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    if interactive.get("type") == "button_reply":
                        reply = interactive["button_reply"]
                        events.append({
                            "from": phone,
                            "type": "interactive",
                            "text": reply["title"],
                            "button_id": reply["id"],
                            "media_id": None,
                        })
                    elif interactive.get("type") == "list_reply":
                        reply = interactive["list_reply"]
                        events.append({
                            "from": phone,
                            "type": "interactive",
                            "text": reply["title"],
                            "button_id": reply["id"],
                            "media_id": None,
                        })
    return events
