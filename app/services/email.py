"""
Email service via Resend — official introductions between matched users
https://resend.com
"""
import httpx
from app.core.config import settings
from app.db.models import User

RESEND_BASE = "https://api.resend.com"


async def send_introduction(user_a: User, user_b: User) -> str:
    """
    Send a formal email introduction between two matched users.
    Returns the Resend email ID.
    """
    subject = f"Introduction: {user_a.name or 'Your match'} ↔ {user_b.name or 'Your match'} via Really"

    body_html = _build_intro_email(user_a, user_b)

    # Send to both in one request (reply-all connects them)
    payload = {
        "from": f"Really <introductions@{settings.EMAIL_FROM_DOMAIN}>",
        "to": [e for e in [user_a.email, user_b.email] if e],
        "reply_to": [e for e in [user_a.email, user_b.email] if e],
        "subject": subject,
        "html": body_html,
    }

    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{RESEND_BASE}/emails",
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        return r.json().get("id", "")


def _build_intro_email(user_a: User, user_b: User) -> str:
    name_a = user_a.name or "there"
    name_b = user_b.name or "there"

    a_summary = _user_summary(user_a)
    b_summary = _user_summary(user_b)

    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <style>
    body {{ font-family: Inter, -apple-system, sans-serif; color: #111; background: #fff; margin: 0; padding: 0; }}
    .container {{ max-width: 560px; margin: 40px auto; padding: 0 24px; }}
    .logo {{ font-size: 18px; font-weight: 700; color: #16a34a; margin-bottom: 32px; }}
    h1 {{ font-size: 22px; font-weight: 700; margin: 0 0 8px; }}
    p {{ font-size: 15px; line-height: 1.6; color: #374151; margin: 12px 0; }}
    .card {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 12px; padding: 20px 24px; margin: 20px 0; }}
    .card h3 {{ font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #6b7280; margin: 0 0 6px; }}
    .card p {{ margin: 4px 0; font-size: 14px; color: #111; }}
    .footer {{ font-size: 12px; color: #9ca3af; margin-top: 40px; border-top: 1px solid #f3f4f6; padding-top: 20px; }}
    .cta {{ background: #16a34a; color: white; display: inline-block; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 14px; margin-top: 16px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="logo">really.ai</div>

    <h1>You've been connected 🏡</h1>
    <p>Hi {name_a} and {name_b},</p>
    <p>Really found a match between you two. Both of you expressed interest in connecting, so here's a formal introduction — just hit reply to start the conversation.</p>

    <div class="card">
      <h3>{name_a}</h3>
      {a_summary}
    </div>

    <div class="card">
      <h3>{name_b}</h3>
      {b_summary}
    </div>

    <p>You're both on this email — just reply all to get the conversation started. Good luck!</p>

    <div class="footer">
      <p>This introduction was made by <strong>really.ai</strong>, your AI real estate superconnecter.</p>
    </div>
  </div>
</body>
</html>
"""


def _user_summary(user: User) -> str:
    lines = []
    if user.role:
        lines.append(f"<p><strong>Role:</strong> {user.role.value.title()}</p>")
    if user.location:
        lines.append(f"<p><strong>Location:</strong> {user.location}</p>")
    if user.budget_min or user.budget_max:
        lo = f"${user.budget_min:,.0f}" if user.budget_min else ""
        hi = f"${user.budget_max:,.0f}" if user.budget_max else ""
        budget = " – ".join(filter(None, [lo, hi]))
        lines.append(f"<p><strong>Budget:</strong> {budget}</p>")
    if user.property_types:
        lines.append(f"<p><strong>Property types:</strong> {user.property_types}</p>")
    if user.timeline:
        lines.append(f"<p><strong>Timeline:</strong> {user.timeline}</p>")
    if user.requirements:
        lines.append(f"<p><strong>Looking for:</strong> {user.requirements}</p>")
    if user.listing_address:
        lines.append(f"<p><strong>Listing:</strong> {user.listing_address}</p>")
    if user.listing_price:
        lines.append(f"<p><strong>Asking price:</strong> ${user.listing_price:,.0f}</p>")
    return "\n".join(lines) if lines else "<p>Details gathered via call.</p>"
