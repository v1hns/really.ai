"""
really.ai — Interactive terminal demo

Simulates the full WhatsApp flow without needing a WhatsApp Business number.
Two modes:
  1. Single-user chat  (python demo.py)
  2. Two-user match demo  (python demo.py --match)

Uses the real AI and matching engine — just needs ANTHROPIC_API_KEY in .env
"""
import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# ── make sure we can import app modules ──────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

# load .env before importing app modules
from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.rule import Rule
from rich import print as rprint

from sqlmodel import Session, select

from app.core.config import settings
from app.db.engine import create_db, engine
from app.db.models import User, Message, Match, ConversationState, UserRole
from app.services import ai, matching

console = Console()

PHONE_A = "demo_user_a"
PHONE_B = "demo_user_b"

DEMO_SELLER_SCRIPT = [
    "seller",
    "My name is Jordan",
    "123 Maple Street, Austin TX",
    "3 bed 2 bath single family home",
    "Asking $480,000. Original 1960s build, fully renovated kitchen",
    "Looking to close within 60 days",
]


# ─── DB helpers ──────────────────────────────────────────────────────────────

def _get_or_create(phone: str) -> User:
    with Session(engine) as s:
        user = s.exec(select(User).where(User.phone == phone)).first()
        if not user:
            user = User(phone=phone, last_active=datetime.utcnow())
            s.add(user)
            s.commit()
            s.refresh(user)
        return user


def _get_user(phone: str) -> User | None:
    with Session(engine) as s:
        return s.exec(select(User).where(User.phone == phone)).first()


def _get_history(user_id: int) -> list[Message]:
    with Session(engine) as s:
        return s.exec(
            select(Message).where(Message.user_id == user_id).order_by(Message.created_at)
        ).all()


def _save_messages(user_id: int, user_text: str, assistant_text: str):
    with Session(engine) as s:
        s.add(Message(user_id=user_id, role="user", content=user_text))
        s.add(Message(user_id=user_id, role="assistant", content=assistant_text))
        s.commit()


def _apply_profile(phone: str, update: dict):
    from app.core.handler import _apply_profile_update
    with Session(engine) as s:
        user = s.exec(select(User).where(User.phone == phone)).first()
        if user and update:
            _apply_profile_update(user, update, s)


def _find_matches(phone: str) -> list[tuple[User, float, str]]:
    with Session(engine) as s:
        user = s.exec(select(User).where(User.phone == phone)).first()
        if not user:
            return []
        return matching.find_matches(user, s)


# ─── display helpers ─────────────────────────────────────────────────────────

def _bubble(text: str, role: str, name: str = "You") -> Panel:
    if role == "user":
        return Panel(
            Text(text, style="white"),
            title=f"[bold green]{name}[/]",
            title_align="right",
            border_style="green",
            padding=(0, 1),
        )
    return Panel(
        Text(text, style="white"),
        title="[bold cyan]🏡 Really[/]",
        title_align="left",
        border_style="cyan",
        padding=(0, 1),
    )


def _show_profile(user: User):
    table = Table(title=f"Profile — {user.phone}", show_header=False, box=None, padding=(0, 1))
    table.add_column("Field", style="dim")
    table.add_column("Value", style="bold")
    rows = [
        ("Name", user.name or "—"),
        ("Role", user.role.value),
        ("State", user.state.value),
        ("Location", user.location or "—"),
        ("Budget", f"${user.budget_min:,.0f} – ${user.budget_max:,.0f}"
            if user.budget_min and user.budget_max else user.budget_min or "—"),
        ("Property types", user.property_types or "—"),
        ("Bedrooms", str(user.bedrooms) if user.bedrooms else "—"),
        ("Timeline", user.timeline or "—"),
        ("Requirements", (user.requirements or "—")[:60]),
        ("Listing", user.listing_address or "—"),
        ("Listing price", f"${user.listing_price:,.0f}" if user.listing_price else "—"),
    ]
    for k, v in rows:
        table.add_row(k, v)
    console.print(table)


def _show_match_banner(matched_user: User, score: float, reason: str):
    console.print()
    console.print(Rule("[bold yellow]✨ Match Found![/]", style="yellow"))
    console.print(Panel(
        f"[bold]Matched with:[/] {matched_user.name or matched_user.phone}\n"
        f"[bold]Role:[/] {matched_user.role.value}\n"
        f"[bold]Location:[/] {matched_user.location}\n"
        f"[bold]Score:[/] {score:.0%}\n"
        f"[bold]Reason:[/] {reason}",
        title="[yellow]🏡 Really found a connection[/]",
        border_style="yellow",
    ))
    console.print()


# ─── core chat loop ──────────────────────────────────────────────────────────

async def chat_turn(phone: str, user_input: str, display_name: str = "You") -> str:
    """Run one turn of the conversation and return the assistant reply."""
    user = _get_or_create(phone)
    history = _get_history(user.id)

    system_extra = (
        f"User state: {user.state.value}. "
        f"User role: {user.role.value}. "
        f"Profile so far: location={user.location}, budget={user.budget_min}-{user.budget_max}, "
        f"property_types={user.property_types}, requirements={user.requirements}."
    )

    reply, profile_update = await ai.get_reply(user, history, user_input, system_extra)
    _save_messages(user.id, user_input, reply)

    if profile_update:
        _apply_profile(phone, profile_update)

    return reply


def _check_for_match(phone: str) -> list[tuple[User, float, str]]:
    user = _get_user(phone)
    if user and user.state == ConversationState.ACTIVE:
        return _find_matches(phone)
    return []


# ─── modes ───────────────────────────────────────────────────────────────────

async def run_single():
    """Interactive single-user chat."""
    console.print(Panel(
        "[bold cyan]really.ai[/] [dim]— WhatsApp Real Estate Superconnecter[/]\n"
        "[dim]Terminal Demo · Single-User Mode[/]\n\n"
        "Type your messages below. Commands: [bold]/profile[/] · [bold]/quit[/]",
        border_style="cyan",
    ))
    console.print()

    # Welcome
    welcome = (
        "👋 Hey! I'm Really — your AI real estate superconnecter.\n\n"
        "I'll get to know what you need, then match you with the right people "
        "(buyers, sellers, renters, landlords, agents, or investors) in your market.\n\n"
        "To start — are you looking to buy, sell, rent, rent out a property, "
        "find clients as an agent, or invest?"
    )
    console.print(_bubble(welcome, "assistant"))
    console.print()

    while True:
        try:
            user_input = Prompt.ask("[bold green]You[/]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/]")
            break

        if user_input.strip().lower() == "/quit":
            console.print("[dim]Goodbye![/]")
            break
        if user_input.strip().lower() == "/profile":
            user = _get_user(PHONE_A)
            if user:
                _show_profile(user)
            continue
        if not user_input.strip():
            continue

        console.print(_bubble(user_input, "user"))
        console.print()

        with console.status("[cyan]Really is thinking...[/]", spinner="dots"):
            reply = await chat_turn(PHONE_A, user_input)

        console.print(_bubble(reply, "assistant"))
        console.print()

        # Show match notification if it fires
        matches = _check_for_match(PHONE_A)
        for matched_user, score, reason in matches:
            _show_match_banner(matched_user, score, reason)
            intro = ai.build_intro_message(_get_user(PHONE_A), matched_user)
            console.print(_bubble(
                f"🏡 *Great news — I found someone you should meet!*\n\n{intro}\n\n"
                "They've been notified about you. Should I share your contact with them?",
                "assistant",
            ))
            console.print()


async def run_match_demo():
    """
    Two-persona demo that shows the full match flow:
      User A — live interactive (you play this role)
      User B — auto-scripted seller (seeded silently in the background)
    """
    console.print(Panel(
        "[bold cyan]really.ai[/] [dim]— Match Demo Mode[/]\n\n"
        "You are [bold green]Alex[/] (a buyer).\n"
        "In the background, [bold yellow]Jordan[/] (a seller in Austin) will be seeded.\n"
        "When your profile is complete, Really will match you and send introductions.\n\n"
        "Commands: [bold]/profile[/] · [bold]/both[/] · [bold]/quit[/]",
        border_style="cyan",
    ))
    console.print()

    # Silently seed the seller
    console.print("[dim]Seeding seller profile in the background...[/]")
    for msg in DEMO_SELLER_SCRIPT:
        await chat_turn(PHONE_B, msg, display_name="Jordan")
    console.print("[dim]✓ Seller (Jordan) ready.[/]")
    console.print()

    # Start buyer conversation
    welcome = (
        "👋 Hey! I'm Really — your AI real estate superconnecter.\n\n"
        "Tell me — are you looking to buy, sell, rent, or something else?"
    )
    console.print(_bubble(welcome, "assistant"))
    console.print()

    while True:
        try:
            user_input = Prompt.ask("[bold green]Alex (you)[/]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Demo ended.[/]")
            break

        if user_input.strip().lower() == "/quit":
            break
        if user_input.strip().lower() == "/profile":
            user = _get_user(PHONE_A)
            if user:
                _show_profile(user)
            continue
        if user_input.strip().lower() == "/both":
            console.print("[bold]Alex:[/]")
            u = _get_user(PHONE_A)
            if u: _show_profile(u)
            console.print("[bold]Jordan:[/]")
            u = _get_user(PHONE_B)
            if u: _show_profile(u)
            continue
        if not user_input.strip():
            continue

        console.print(_bubble(user_input, "user", name="Alex"))
        console.print()

        with console.status("[cyan]Really is thinking...[/]", spinner="dots"):
            reply = await chat_turn(PHONE_A, user_input, display_name="Alex")

        console.print(_bubble(reply, "assistant"))
        console.print()

        # Check for match
        matches = _check_for_match(PHONE_A)
        for matched_user, score, reason in matches:
            _show_match_banner(matched_user, score, reason)

            alex = _get_user(PHONE_A)
            intro_to_alex = ai.build_intro_message(alex, matched_user)
            intro_to_jordan = ai.build_intro_message(matched_user, alex)

            console.print(Rule("[cyan]Message sent to Alex[/]", style="cyan"))
            console.print(_bubble(
                f"🏡 *Great news — I found someone you should meet!*\n\n{intro_to_alex}\n\n"
                "They've been notified about you. Reply YES if you'd like me to share your contact.",
                "assistant",
            ))
            console.print()
            console.print(Rule("[yellow]Message sent to Jordan[/]", style="yellow"))
            console.print(Panel(
                f"🏡 *I found a great connection for you!*\n\n{intro_to_jordan}\n\n"
                "Reply YES if you'd like me to share your contact with them.",
                title="[yellow]Jordan's WhatsApp[/]",
                border_style="yellow",
            ))
            console.print()


# ─── entry point ─────────────────────────────────────────────────────────────

def _wipe_demo_users():
    """Clean up demo users from previous runs."""
    with Session(engine) as s:
        for phone in (PHONE_A, PHONE_B):
            user = s.exec(select(User).where(User.phone == phone)).first()
            if user:
                s.exec(  # type: ignore
                    select(Message).where(Message.user_id == user.id)
                )
                # Delete messages
                for msg in s.exec(select(Message).where(Message.user_id == user.id)).all():
                    s.delete(msg)
                # Delete matches
                for m in s.exec(select(Match).where(
                    (Match.initiator_id == user.id) | (Match.target_id == user.id)
                )).all():
                    s.delete(m)
                s.delete(user)
        s.commit()


def main():
    parser = argparse.ArgumentParser(description="really.ai terminal demo")
    parser.add_argument("--match", action="store_true", help="Run two-persona match demo")
    parser.add_argument("--keep", action="store_true", help="Keep previous demo session data")
    args = parser.parse_args()

    create_db()

    if not args.keep:
        _wipe_demo_users()

    try:
        if args.match:
            asyncio.run(run_match_demo())
        else:
            asyncio.run(run_single())
    except KeyboardInterrupt:
        console.print("\n[dim]Demo exited.[/]")


if __name__ == "__main__":
    main()
