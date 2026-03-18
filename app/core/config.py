"""
Configuration — loaded from environment variables / .env file
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # WhatsApp Cloud API
    WHATSAPP_PHONE_NUMBER_ID: str
    WHATSAPP_ACCESS_TOKEN: str
    WHATSAPP_VERIFY_TOKEN: str  # arbitrary secret you choose for webhook verification

    # Anthropic (optional — no longer used for AI, kept for future use)
    ANTHROPIC_API_KEY: str = ""

    # OpenAI — Whisper transcription + TTS voice replies (optional)
    OPENAI_API_KEY: str = ""

    # Groq — AI conversations (free tier, llama-3.3-70b)
    GROQ_API_KEY: str

    # VAPI — AI phone calls for intake
    VAPI_API_KEY: str = ""
    VAPI_PHONE_NUMBER_ID: str = ""  # VAPI phone number ID (not the E.164 number)

    # Resend — email introductions
    RESEND_API_KEY: str = ""
    EMAIL_FROM_DOMAIN: str = "really.ai"  # domain verified in Resend
    VOICE_REPLIES: bool = False   # set True to reply with audio notes instead of text

    PUBLIC_BASE_URL: str = ""      # e.g. https://abc123.ngrok.io — used to build webhook URLs

    # App
    DATABASE_URL: str = "sqlite:///./really.db"
    DEBUG: bool = False
    BOT_NAME: str = "Really"
    BOT_PHONE_DISPLAY: str = "Really AI"

    # Matching
    MATCH_SCORE_THRESHOLD: float = 0.6  # minimum score to trigger an introduction
    MAX_MATCHES_PER_USER: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
