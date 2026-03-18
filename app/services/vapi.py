"""
VAPI client — trigger outbound AI phone calls for intake
https://docs.vapi.ai
"""
import httpx
from app.core.config import settings

VAPI_BASE = "https://api.vapi.ai"

INTAKE_SYSTEM_PROMPT = """You are Really, an AI real estate superconnecter. You're calling someone \
who just signed up on really.ai. Your job is to learn enough about them to find a great match.

Be warm, direct, and efficient. Ask one question at a time. No recaps. No filler.

Based on their role, collect:
- Buyers/Renters: location, budget range, property type, bedrooms, timeline
- Sellers/Landlords: property address, price, property type, availability
- Agents: market/area, specialization, what clients they need
- Investors: strategy, target markets, budget, property types

When you have enough info (role + location + one key detail), say:
"Perfect — I have everything I need. I'll text you as soon as I find a match. Talk soon!"
Then end the call."""

STRUCTURED_DATA_SCHEMA = {
    "type": "object",
    "properties": {
        "role": {"type": "string", "enum": ["buyer", "seller", "renter", "landlord", "agent", "investor"]},
        "location": {"type": "string"},
        "budget_min": {"type": "number"},
        "budget_max": {"type": "number"},
        "property_types": {"type": "string"},
        "bedrooms": {"type": "number"},
        "timeline": {"type": "string"},
        "requirements": {"type": "string"},
        "listing_address": {"type": "string"},
        "listing_price": {"type": "number"},
        "listing_description": {"type": "string"},
    },
    "required": ["role", "location"],
}


async def start_intake_call(phone: str, name: str, role: str) -> str:
    """
    Initiate a VAPI outbound call for intake.
    Returns the VAPI call ID.
    """
    role_context = _role_context(role)

    payload = {
        "assistant": {
            "model": {
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "systemPrompt": INTAKE_SYSTEM_PROMPT + f"\n\nThis person signed up as a {role}. {role_context}",
            },
            "voice": {
                "provider": "playht",
                "voiceId": "jennifer",
            },
            "firstMessage": f"Hey {name}! This is Really — thanks for signing up. I just need a couple minutes to learn what you're looking for so I can find you the perfect match. Sound good?",
            "endCallMessage": "Perfect — I have everything I need. I'll text you when I find a match. Talk soon!",
            "analysisPlan": {
                "structuredDataPrompt": "Extract the user's real estate profile from this conversation.",
                "structuredDataSchema": STRUCTURED_DATA_SCHEMA,
                "summaryPrompt": "Summarize what this person is looking for in real estate in 1-2 sentences.",
            },
            "serverUrl": f"{settings.PUBLIC_BASE_URL}/api/vapi/webhook",
        },
        "phoneNumberId": settings.VAPI_PHONE_NUMBER_ID,
        "customer": {
            "number": phone,
            "name": name,
        },
    }

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{VAPI_BASE}/call/phone",
            headers={
                "Authorization": f"Bearer {settings.VAPI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        return r.json().get("id", "")


def _role_context(role: str) -> str:
    ctx = {
        "buyer": "Focus on: target location, budget range, property type, bedrooms, must-haves, timeline.",
        "seller": "Focus on: property address, asking price, property type, key features, timeline to sell.",
        "renter": "Focus on: neighborhood, monthly budget, property type, bedrooms, move-in date.",
        "landlord": "Focus on: property address, monthly rent, property type, availability date.",
        "agent": "Focus on: market specialization, years of experience, what clients they're looking for.",
        "investor": "Focus on: investment strategy, target markets, budget, preferred property types.",
    }
    return ctx.get(role, "")
