"""
Voice service — transcription (Whisper) + text-to-speech (OpenAI TTS)

WhatsApp voice flow:
  incoming audio msg → download media → transcribe → treat as text
  outgoing voice note → TTS → upload to WhatsApp media → send audio msg
"""
import io
import tempfile
import httpx
from openai import AsyncOpenAI
from app.core.config import settings

_openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"

# WhatsApp audio mime types it sends us
SUPPORTED_AUDIO_TYPES = {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/ogg; codecs=opus"}


# ─── incoming: transcribe ───────────────────────────────────────────────────

async def download_whatsapp_media(media_id: str) -> tuple[bytes, str]:
    """Download a WhatsApp media file and return (content_bytes, mime_type)."""
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}

    # Step 1: resolve media URL
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{GRAPH_API_BASE}/{media_id}",
            headers=headers,
        )
        r.raise_for_status()
        meta = r.json()
        media_url = meta["url"]
        mime_type = meta.get("mime_type", "audio/ogg")

    # Step 2: download the actual file
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(media_url, headers=headers)
        r.raise_for_status()
        return r.content, mime_type


async def transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """Transcribe audio bytes using OpenAI Whisper. Returns transcript text."""
    # Whisper needs a file-like object with a name
    ext = _ext_from_mime(mime_type)
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = f"audio.{ext}"

    transcript = await _openai.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="en",
    )
    return transcript.text.strip()


async def transcribe_whatsapp_audio(media_id: str) -> str:
    """Download a WhatsApp audio message and return its transcript."""
    audio_bytes, mime_type = await download_whatsapp_media(media_id)
    return await transcribe(audio_bytes, mime_type)


# ─── outgoing: TTS ──────────────────────────────────────────────────────────

async def synthesize(text: str, voice: str = "nova") -> bytes:
    """Convert text to speech using OpenAI TTS. Returns MP3 bytes.

    Voices: alloy, echo, fable, onyx, nova, shimmer
    'nova' is warm and conversational — good fit for a real estate concierge.
    """
    response = await _openai.audio.speech.create(
        model="tts-1",
        voice=voice,
        input=text,
        response_format="mp3",
    )
    return response.content


async def upload_whatsapp_media(audio_bytes: bytes, mime_type: str = "audio/mpeg") -> str:
    """Upload audio to WhatsApp media endpoint and return media_id."""
    url = f"{GRAPH_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            url,
            headers=headers,
            data={"messaging_product": "whatsapp"},
            files={"file": ("reply.mp3", audio_bytes, mime_type)},
        )
        r.raise_for_status()
        return r.json()["id"]


async def send_voice_reply(to: str, text: str) -> dict:
    """Synthesize text → upload → send as WhatsApp audio message."""
    from app.services.whatsapp import send_audio  # avoid circular at module level
    mp3_bytes = await synthesize(text)
    media_id = await upload_whatsapp_media(mp3_bytes)
    return await send_audio(to, media_id)


# ─── helpers ────────────────────────────────────────────────────────────────

def _ext_from_mime(mime_type: str) -> str:
    mapping = {
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "mp4",
        "audio/wav": "wav",
        "audio/webm": "webm",
    }
    base = mime_type.split(";")[0].strip()
    return mapping.get(base, "ogg")
