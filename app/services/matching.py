"""
Matching engine — finds compatible real estate pairs
"""
from sqlmodel import Session, select
from app.db.models import User, Match, UserRole, ConversationState
from app.core.config import settings


# Roles that can be matched together
COMPATIBLE_PAIRS = {
    UserRole.BUYER: [UserRole.SELLER, UserRole.AGENT],
    UserRole.SELLER: [UserRole.BUYER, UserRole.AGENT],
    UserRole.RENTER: [UserRole.LANDLORD, UserRole.AGENT],
    UserRole.LANDLORD: [UserRole.RENTER, UserRole.AGENT],
    UserRole.AGENT: [UserRole.BUYER, UserRole.SELLER, UserRole.RENTER, UserRole.LANDLORD, UserRole.INVESTOR],
    UserRole.INVESTOR: [UserRole.AGENT, UserRole.SELLER],
}


def _location_score(a: str | None, b: str | None) -> float:
    """Simple token overlap for location matching."""
    if not a or not b:
        return 0.3  # partial credit — assume flexible
    a_tokens = set(a.lower().split())
    b_tokens = set(b.lower().split())
    overlap = a_tokens & b_tokens
    if not overlap:
        return 0.0
    return len(overlap) / max(len(a_tokens), len(b_tokens))


def _budget_score(buyer: User, seller: User) -> float:
    """Check if buyer budget overlaps with seller/landlord price."""
    # Seller side
    s_price = seller.listing_price or seller.budget_min  # landlord uses budget_min for rent
    if not s_price:
        return 0.3

    # Buyer side
    b_max = buyer.budget_max or buyer.budget_min
    b_min = buyer.budget_min or 0

    if not b_max:
        return 0.3

    if b_min <= s_price <= b_max:
        return 1.0
    # Partial credit if close
    diff = min(abs(s_price - b_min), abs(s_price - b_max))
    tolerance = b_max * 0.2  # 20% tolerance
    if diff <= tolerance:
        return 0.6
    return 0.0


def _property_type_score(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.5
    a_types = set(a.lower().split(","))
    b_types = set(b.lower().split(","))
    return 1.0 if a_types & b_types else 0.0


def score_pair(user_a: User, user_b: User) -> float:
    """Score compatibility between two users (0.0 – 1.0)."""
    if user_b.role not in COMPATIBLE_PAIRS.get(user_a.role, []):
        return 0.0

    loc = _location_score(user_a.location, user_b.location)
    if loc == 0.0:
        return 0.0  # different markets = no match

    prop = _property_type_score(user_a.property_types, user_b.property_types)

    # Budget scoring depends on pair type
    budget = 0.5
    if user_a.role in (UserRole.BUYER, UserRole.RENTER) and user_b.role in (UserRole.SELLER, UserRole.LANDLORD):
        budget = _budget_score(user_a, user_b)
    elif user_a.role in (UserRole.SELLER, UserRole.LANDLORD) and user_b.role in (UserRole.BUYER, UserRole.RENTER):
        budget = _budget_score(user_b, user_a)

    # Weighted average
    score = (loc * 0.4) + (budget * 0.35) + (prop * 0.25)
    return round(score, 3)


def find_matches(user: User, session: Session) -> list[tuple[User, float, str]]:
    """
    Find top matches for a given user.
    Returns list of (matched_user, score, reason).
    """
    compatible_roles = COMPATIBLE_PAIRS.get(user.role, [])
    if not compatible_roles:
        return []

    candidates = session.exec(
        select(User).where(
            User.id != user.id,
            User.role.in_(compatible_roles),  # type: ignore
            User.state.in_([ConversationState.ACTIVE, ConversationState.MATCHED]),  # type: ignore
            User.opt_in == True,
        )
    ).all()

    # Exclude already-introduced pairs
    existing_match_ids = {
        m.target_id
        for m in session.exec(
            select(Match).where(Match.initiator_id == user.id, Match.introduced == True)
        ).all()
    }

    results = []
    for candidate in candidates:
        if candidate.id in existing_match_ids:
            continue
        s = score_pair(user, candidate)
        if s >= settings.MATCH_SCORE_THRESHOLD:
            reason = _build_reason(user, candidate, s)
            results.append((candidate, s, reason))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[: settings.MAX_MATCHES_PER_USER]


def _build_reason(a: User, b: User, score: float) -> str:
    parts = []
    if a.location and b.location:
        parts.append(f"same market ({a.location})")
    if score >= 0.8:
        parts.append("strong budget overlap")
    elif score >= 0.65:
        parts.append("compatible budget range")
    if a.property_types and b.property_types:
        parts.append("matching property types")
    return ", ".join(parts) or "general compatibility"
