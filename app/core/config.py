"""
Configuration — loaded from environment variables / .env file
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # WhatsApp Cloud API
    WHATSAPP_PHONE_NUMBER_ID: str
    WHATSAPP_ACCESS_TOKEN: str
    WHATSAPP_VERIFY_TOKEN: str  # arbitrary secret you choose for webhook verification

    # Anthropic
    ANTHROPIC_API_KEY: str

    # OpenAI (Whisper transcription + TTS voice replies)
    OPENAI_API_KEY: str = ""
    VOICE_REPLIES: bool = False   # set True to reply with audio notes instead of text

    # Twilio (phone calls)
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""  # e.g. +14155551234
    PUBLIC_BASE_URL: str = ""      # e.g. https://abc123.ngrok.io — used to build TwiML callback URLs

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
