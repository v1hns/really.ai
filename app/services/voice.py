"""
Voice service — transcription (Whisper) + text-to-speech (OpenAI TTS)

Telegram voice flow:
  incoming voice msg → download via getFile → transcribe → treat as text
  outgoing voice note → TTS → send audio directly via sendAudio
"""
import io
import httpx
from openai import AsyncOpenAI
from app.core.config import settings

_openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

API_BASE = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"
FILE_BASE = f"https://api.telegram.org/file/bot{settings.TELEGRAM_BOT_TOKEN}"


# ─── incoming: transcribe ───────────────────────────────────────────────────

async def download_telegram_media(file_id: str) -> tuple[bytes, str]:
    """Download a Telegram media file via getFile and return (content_bytes, mime_type)."""
    # Step 1: resolve file_path
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{API_BASE}/getFile", params={"file_id": file_id})
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]

    # Step 2: download the file
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{FILE_BASE}/{file_path}")
        r.raise_for_status()
        # Telegram voice notes are always OGG Opus
        return r.content, "audio/ogg"


async def transcribe(audio_bytes: bytes, mime_type: str = "audio/ogg") -> str:
    """Transcribe audio bytes using OpenAI Whisper. Returns transcript text."""
    ext = _ext_from_mime(mime_type)
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = f"audio.{ext}"

    transcript = await _openai.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="en",
    )
    return transcript.text.strip()


async def transcribe_telegram_audio(file_id: str) -> str:
    """Download a Telegram voice/audio message and return its transcript."""
    audio_bytes, mime_type = await download_telegram_media(file_id)
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


async def send_voice_reply(to: str, text: str) -> dict:
    """Synthesize text → send as Telegram audio message."""
    from app.services.telegram import send_audio
    mp3_bytes = await synthesize(text)
    return await send_audio(to, mp3_bytes)


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
