"""
Database models for really.ai
"""
from datetime import datetime
from enum import Enum
from typing import Optional
from sqlmodel import Field, SQLModel, Relationship


class UserRole(str, Enum):
    BUYER = "buyer"
    SELLER = "seller"
    RENTER = "renter"
    LANDLORD = "landlord"
    AGENT = "agent"
    INVESTOR = "investor"
    UNKNOWN = "unknown"


class ConversationState(str, Enum):
    GREETING = "greeting"
    ROLE_SELECTION = "role_selection"
    PROFILE_BUILDING = "profile_building"
    ACTIVE = "active"
    MATCHED = "matched"


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    phone: str = Field(unique=True, index=True)
    name: Optional[str] = None
    role: UserRole = UserRole.UNKNOWN
    state: ConversationState = ConversationState.GREETING

    # Profile fields (populated conversationally)
    location: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    property_types: Optional[str] = None   # comma-separated: "apartment,condo,house"
    bedrooms: Optional[int] = None
    requirements: Optional[str] = None     # free-text summary of needs
    timeline: Optional[str] = None         # e.g. "3 months", "ASAP"

    # For sellers/landlords
    listing_address: Optional[str] = None
    listing_price: Optional[float] = None
    listing_description: Optional[str] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    opt_in: bool = True

    messages: list["Message"] = Relationship(back_populates="user")
    sent_matches: list["Match"] = Relationship(
        back_populates="initiator",
        sa_relationship_kwargs={"foreign_keys": "[Match.initiator_id]"},
    )
    received_matches: list["Match"] = Relationship(
        back_populates="target",
        sa_relationship_kwargs={"foreign_keys": "[Match.target_id]"},
    )


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    role: str  # "user" or "assistant"
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    user: Optional[User] = Relationship(back_populates="messages")


class Match(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    initiator_id: int = Field(foreign_key="user.id")
    target_id: int = Field(foreign_key="user.id")
    score: float = 0.0
    reason: Optional[str] = None
    introduced: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    initiator: Optional[User] = Relationship(
        back_populates="sent_matches",
        sa_relationship_kwargs={"foreign_keys": "[Match.initiator_id]"},
    )
    target: Optional[User] = Relationship(
        back_populates="received_matches",
        sa_relationship_kwargs={"foreign_keys": "[Match.target_id]"},
    )
