# really.ai — WhatsApp Real Estate Superconnecter

**really.ai is an AI-powered real estate matchmaker that runs on WhatsApp and phone calls.** Message or call the number, tell it what you need, and it connects you with the right person — buyer meets seller, renter meets landlord, investor meets agent — automatically.

## TL;DR — how it runs

```
User texts/calls → Claude asks intake questions → profile stored in DB
→ matching engine scores compatibility → both parties get an intro (WhatsApp + call)
```

1. **User contacts Really** — via WhatsApp message, voice note, or phone call
2. **Claude runs intake** — asks role (buyer / seller / renter / landlord / agent / investor), location, budget, property type, timeline
3. **Profile is built** — Claude extracts structured data from natural conversation and saves it
4. **Matching fires** — scored against all other active users (location 40%, budget 35%, property type 25%)
5. **Intro sent** — both parties get an AI-written WhatsApp message; if Twilio is configured, Really calls them too

**To demo it locally (no WhatsApp needed):**
```bash
python demo.py          # single-user chat
python demo.py --match  # two-persona demo — watch a buyer + seller get matched live
```

**To run the full server:**
```bash
cp .env.example .env    # fill in API keys
uvicorn main:app --reload --port 8000
ngrok http 8000         # expose for webhooks
```

## Stack

| Layer | Technology |
|---|---|
| Messaging | WhatsApp Cloud API (Meta) |
| AI | Claude claude-sonnet-4-6 (Anthropic) |
| Backend | FastAPI + Python |
| Database | SQLite (drop-in Postgres swap via `DATABASE_URL`) |

## Setup

### 1. Prerequisites

- Python 3.11+
- A Meta developer account with a WhatsApp Business App
- An Anthropic API key

### 2. Install

```bash
cd really.ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Run locally

```bash
uvicorn main:app --reload --port 8000
```

Expose it publicly for Meta's webhook (use ngrok during dev):

```bash
ngrok http 8000
```

### 5. Register webhook with Meta

In your Meta App Dashboard:
- Callback URL: `https://your-ngrok-url.ngrok.io/api/webhook`
- Verify Token: same as `WHATSAPP_VERIFY_TOKEN` in your `.env`
- Subscribe to: `messages`

## Project structure

```
really.ai/
├── main.py                  # FastAPI app entry point
├── app/
│   ├── api/
│   │   └── webhook.py       # WhatsApp webhook (GET verify + POST receive)
│   ├── core/
│   │   ├── config.py        # Settings (pydantic-settings / .env)
│   │   └── handler.py       # Main message orchestration loop
│   ├── db/
│   │   ├── models.py        # SQLModel data models
│   │   └── engine.py        # DB engine + session
│   └── services/
│       ├── whatsapp.py      # WhatsApp Cloud API client
│       ├── ai.py            # Claude conversation manager
│       └── matching.py      # Compatibility scoring & match finding
├── requirements.txt
└── .env.example
```

## Matching logic

Scores are 0.0–1.0 based on:
- **Location overlap** (40%) — tokenized city/neighborhood comparison
- **Budget compatibility** (35%) — buyer max vs. seller price with 20% tolerance
- **Property type overlap** (25%) — apartment / house / condo / etc.

Introductions fire when score ≥ 0.6 (configurable via `MATCH_SCORE_THRESHOLD`).

## Deployment

Any Python host works. Recommended: Railway, Fly.io, or a basic VPS.

```bash
# Production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

For Postgres, set `DATABASE_URL=postgresql://user:pass@host/db` in `.env`.
