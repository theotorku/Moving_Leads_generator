from datetime import date, datetime
from enum import Enum
from typing import Annotated, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ZipCode = Annotated[str, Field(pattern=r"^\d{5}$")]
PhoneNumber = Annotated[str, Field(min_length=7, max_length=20, pattern=r"^[0-9()+\-\s]+$")]


class HomeSize(str, Enum):
    studio = "studio"
    one_bedroom = "1_bedroom"
    two_bedroom = "2_bedroom"
    three_bedroom = "3_bedroom"
    four_plus_bedroom = "4_plus_bedroom"


class LeadUrgency(str, Enum):
    same_week = "same_week"
    this_month = "this_month"
    planning_ahead = "planning_ahead"


class SubscriptionTier(str, Enum):
    starter = "starter"
    professional = "professional"
    enterprise = "enterprise"


class SubscriptionStatus(str, Enum):
    active = "active"
    trialing = "trialing"
    canceled = "canceled"
    past_due = "past_due"
    unpaid = "unpaid"
    incomplete = "incomplete"
    paused = "paused"
    unknown = "unknown"


class LeadStatus(str, Enum):
    available = "available"
    sold = "sold"


class PurchaseType(str, Enum):
    included = "included"
    overage = "overage"


class RouteType(str, Enum):
    local = "local"
    intrastate = "intrastate"
    interstate = "interstate"
    unknown = "unknown"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class MoveComplexity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class LeadSourceChannel(str, Enum):
    direct = "direct"
    organic = "organic"
    google_lsa = "google_lsa"
    google_ads = "google_ads"
    yelp = "yelp"
    angi = "angi"
    thumbtack = "thumbtack"
    realtor_partner = "realtor_partner"
    referral_partner = "referral_partner"
    email = "email"
    social = "social"
    webhook = "webhook"
    manual = "manual"
    unknown = "unknown"


def _require_phone_digits(value: Optional[str]) -> Optional[str]:
    if value and not any(character.isdigit() for character in value):
        raise ValueError("Phone number must include at least one digit.")
    return value

class RawLead(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    full_name: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    phone: PhoneNumber
    move_date: date
    origin_zip: ZipCode
    destination_zip: ZipCode
    home_size: HomeSize
    budget: Annotated[int, Field(gt=0, le=50000)]
    urgency: LeadUrgency

    # Provenance / TCPA consent captured at submission (optional)
    consent_tcpa: bool = False
    consent_text: Optional[str] = None
    source_url: Optional[str] = None
    source_channel: Optional[LeadSourceChannel] = None
    source_medium: Optional[str] = None
    source_campaign: Optional[str] = None
    source_referrer: Optional[str] = None
    source_partner: Optional[str] = None
    landing_page: Optional[str] = None

    @field_validator(
        "consent_text",
        "source_url",
        "source_channel",
        "source_medium",
        "source_campaign",
        "source_referrer",
        "source_partner",
        "landing_page",
        mode="before",
    )
    @classmethod
    def empty_provenance_value_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("phone")
    @classmethod
    def phone_must_include_digits(cls, value: str) -> str:
        return _require_phone_digits(value)

class ScoredLead(RawLead):
    model_config = ConfigDict(use_enum_values=True)

    score: int
    reasoning: str
    booking_probability: Annotated[int, Field(ge=0, le=100)] = 50
    estimated_job_value: Annotated[int, Field(ge=0, le=100000)] = 0
    route_type: RouteType = RouteType.unknown
    move_complexity: MoveComplexity = MoveComplexity.medium
    fraud_risk: RiskLevel = RiskLevel.medium
    missing_info: list[str] = Field(default_factory=list)
    recommended_followup: str = "Call the lead to confirm move details and availability."
    confidence: Annotated[int, Field(ge=0, le=100)] = 50
    best_customer_fit_reason: str = "Match with a customer that has active billing and available lead capacity."

class Customer(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: Optional[UUID] = None
    company_name: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    phone: Optional[PhoneNumber] = None
    stripe_customer_id: Optional[str] = None
    created_at: Optional[datetime] = None

    @field_validator("phone")
    @classmethod
    def optional_phone_must_include_digits(cls, value: Optional[str]) -> Optional[str]:
        return _require_phone_digits(value)

class Subscription(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: Optional[UUID] = None
    customer_id: UUID
    tier: SubscriptionTier
    status: SubscriptionStatus
    leads_included: int
    leads_used: int = 0
    stripe_subscription_id: Optional[str] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    created_at: Optional[datetime] = None

class LeadPurchase(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: Optional[UUID] = None
    lead_id: UUID
    customer_id: UUID
    purchase_type: PurchaseType
    price_paid: float
    purchased_at: Optional[datetime] = None


class CustomerRegistration(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    company_name: Annotated[str, Field(min_length=2, max_length=120)]
    email: EmailStr
    phone: Optional[PhoneNumber] = None
    tier: SubscriptionTier

    @field_validator("phone")
    @classmethod
    def registration_phone_must_include_digits(cls, value: Optional[str]) -> Optional[str]:
        return _require_phone_digits(value)


class RoutingProfileUpdate(BaseModel):
    """A buyer's lead-routing preferences (empty lists = no restriction)."""

    service_zips: list[str] = Field(default_factory=list)
    accepted_route_types: list[str] = Field(default_factory=list)
    accepted_home_sizes: list[str] = Field(default_factory=list)
    min_job_value: Annotated[int, Field(ge=0, le=100000)] = 0
    fmcsa_number: Optional[str] = None


class ScoreResponse(ScoredLead):
    """Response for POST /leads/score: the scored lead plus persistence status."""

    model_config = ConfigDict(use_enum_values=True)

    persisted: bool = True
    persistence_warning: Optional[str] = None
    calibration: Optional[dict] = None
