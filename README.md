# really.ai — AI Real Estate Superconnecter

**really.ai is an AI-powered real estate matchmaker.** Someone fills out a form, gets called immediately by an AI, answers a few questions, and gets connected with the right person — buyer meets seller, renter meets landlord, investor meets agent.

## How it works

```
Form submit (name + phone) → VAPI calls user → 2-min AI intake
→ profile saved → matching engine runs → SMS matched party
→ both say YES → each gets the other's number
```

1. User fills form on the landing page — name, phone, role
2. VAPI calls them immediately, AI asks intake questions
3. Call ends → structured profile saved to DB + exported as JSON
4. Matching engine scores compatibility against everyone in the directory
5. Matched party gets an SMS: "Want to connect? Reply YES or NO"
6. Both say YES → each gets a text with the other's phone number

---

## Setup guide

### 1. Clone & install

```bash
git clone https://github.com/v1hns/really.ai
cd really.ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get your API keys

| Service | URL | What it does | Cost |
|---|---|---|---|
| **Groq** | console.groq.com | AI brain (intake conversations) | Free |
| **VAPI** | dashboard.vapi.ai | AI phone calls | Free trial |
| **WhatsApp Cloud API** | developers.facebook.com | WhatsApp channel (optional) | Free |
| **OpenAI** | platform.openai.com | Voice notes via Whisper/TTS (optional) | Pay-as-you-go |

### 3. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
# Required
GROQ_API_KEY=gsk_...               # from console.groq.com → API Keys
VAPI_API_KEY=...                   # from dashboard.vapi.ai → API Keys
VAPI_PHONE_NUMBER_ID=...           # from dashboard.vapi.ai → Phone Numbers → copy the ID
PUBLIC_BASE_URL=https://xxxx.ngrok.io   # your public URL (see step 5)

# WhatsApp (optional)
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_VERIFY_TOKEN=any_secret_string

# Voice notes (optional)
OPENAI_API_KEY=sk-...
VOICE_REPLIES=false
```

### 4. Run locally

```bash
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** — the landing page is live.

### 5. Expose for webhooks (dev)

VAPI and Twilio need to reach your server. Use ngrok:

```bash
ngrok http 8000
```

Copy the `https://xxxx.ngrok.io` URL and set it as `PUBLIC_BASE_URL` in your `.env`, then restart the server.

### 6. Test it

```bash
# Terminal demo — no keys needed except GROQ_API_KEY
python demo.py          # single user
python demo.py --match  # buyer + seller match demo
```

---

## Project structure

```
really.ai/
├── main.py                      # FastAPI entry point, serves landing page
├── web/
│   └── index.html               # Landing page
├── app/
│   ├── api/
│   │   ├── intake.py            # POST /api/intake/submit → triggers VAPI call
│   │   ├── vapi_webhook.py      # POST /api/vapi/webhook → saves profile, runs matching
│   │   ├── consent.py           # POST /api/consent/sms → YES/NO handler
│   │   ├── webhook.py           # WhatsApp Cloud API webhook
│   │   └── calls.py             # Twilio voice call webhooks
│   ├── core/
│   │   ├── config.py            # All settings (pydantic-settings / .env)
│   │   ├── handler.py           # WhatsApp message orchestration
│   │   └── call_handler.py      # Phone call turn logic
│   ├── db/
│   │   ├── models.py            # User, Match, ConsentRequest, Message
│   │   └── engine.py            # SQLite engine (swap to Postgres via DATABASE_URL)
│   └── services/
│       ├── vapi.py              # VAPI outbound call client
│       ├── ai.py                # Groq conversation manager
│       ├── matching.py          # Compatibility scoring engine
│       ├── whatsapp.py          # WhatsApp Cloud API client
│       ├── voice.py             # Whisper transcription + TTS
│       └── twilio_client.py     # Twilio SMS + call client
├── demo.py                      # Terminal demo (no WhatsApp needed)
├── exports/                     # JSON call profiles (auto-created)
└── .env.example
```

## Matching logic

Scores 0.0–1.0, intro fires at ≥ 0.6:
- **Location** (40%) — token overlap on city/neighborhood
- **Budget** (35%) — buyer max vs. seller price, 20% tolerance
- **Property type** (25%) — apartment / house / condo / etc.

`MATCH_SCORE_THRESHOLD` and `MAX_MATCHES_PER_USER` are configurable in `.env`.

## Deployment

Connect the GitHub repo to **Railway** or **Render** (both have free tiers) — they auto-detect Python and deploy on push. Set all env vars in their dashboard and you're live.

```bash
# Or self-host
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

Swap to Postgres anytime: `DATABASE_URL=postgresql://user:pass@host/db`
