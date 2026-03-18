"""
Telegram Bot API client
https://core.telegram.org/bots/api
"""
import httpx
from app.core.config import settings

API_BASE = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"


async def send_message(chat_id: str, text: str) -> dict:
    """Send a plain text Telegram message."""
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{API_BASE}/sendMessage", json=payload)
        r.raise_for_status()
        return r.json()


async def send_buttons(chat_id: str, body: str, buttons: list[dict]) -> dict:
    """Send a message with inline keyboard buttons.

    buttons = [{"id": "buyer", "title": "Buyer"}]
    """
    keyboard = [
        [{"text": b["title"], "callback_data": b["id"]}] for b in buttons
    ]
    payload = {
        "chat_id": chat_id,
        "text": body,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": keyboard},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{API_BASE}/sendMessage", json=payload)
        r.raise_for_status()
        return r.json()


async def send_list(
    chat_id: str,
    header: str,
    body: str,
    button_label: str,
    sections: list[dict],
) -> dict:
    """Send a message with inline keyboard rows (Telegram equivalent of WhatsApp list).

    Flattens sections/rows into inline keyboard buttons, one per row.
    """
    keyboard = []
    for section in sections:
        for row in section.get("rows", []):
            label = row["title"]
            if row.get("description"):
                label += f" — {row['description']}"
            keyboard.append([{"text": label, "callback_data": row["id"]}])

    text = f"*{header}*\n\n{body}"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": keyboard},
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(f"{API_BASE}/sendMessage", json=payload)
        r.raise_for_status()
        return r.json()


async def send_audio(chat_id: str, audio_bytes: bytes, filename: str = "reply.mp3") -> dict:
    """Send audio bytes as a Telegram audio message."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{API_BASE}/sendAudio",
            data={"chat_id": chat_id},
            files={"audio": (filename, audio_bytes, "audio/mpeg")},
        )
        r.raise_for_status()
        return r.json()


async def answer_callback_query(callback_query_id: str) -> dict:
    """Acknowledge a callback query to dismiss the button spinner."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{API_BASE}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
        )
        r.raise_for_status()
        return r.json()


def parse_incoming(update: dict) -> list[dict]:
    """Extract message events from a Telegram Update object.

    Returns list of dicts matching the same interface as the old WhatsApp parser:
      {
        "from": chat_id (str),
        "type": "text" | "interactive" | "audio",
        "text": str,
        "button_id": str | None,
        "media_id": str | None,
        "callback_query_id": str | None,
      }
    """
    events = []

    # Handle regular messages (text, voice, audio)
    msg = update.get("message")
    if msg:
        chat_id = str(msg["chat"]["id"])

        if "voice" in msg:
            events.append({
                "from": chat_id,
                "type": "audio",
                "text": "",
                "button_id": None,
                "media_id": msg["voice"]["file_id"],
                "callback_query_id": None,
            })
        elif "audio" in msg:
            events.append({
                "from": chat_id,
                "type": "audio",
                "text": "",
                "button_id": None,
                "media_id": msg["audio"]["file_id"],
                "callback_query_id": None,
            })
        elif "text" in msg:
            events.append({
                "from": chat_id,
                "type": "text",
                "text": msg["text"],
                "button_id": None,
                "media_id": None,
                "callback_query_id": None,
            })

    # Handle callback queries (inline button presses)
    cb = update.get("callback_query")
    if cb:
        chat_id = str(cb["message"]["chat"]["id"])
        events.append({
            "from": chat_id,
            "type": "interactive",
            "text": cb.get("data", ""),
            "button_id": cb.get("data"),
            "media_id": None,
            "callback_query_id": cb["id"],
        })

    return events
