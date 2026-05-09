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
    canceled = "canceled"
    past_due = "past_due"


class LeadStatus(str, Enum):
    available = "available"
    sold = "sold"


class PurchaseType(str, Enum):
    included = "included"
    overage = "overage"

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

    @field_validator("phone")
    @classmethod
    def phone_must_include_digits(cls, value: str) -> str:
        if not any(character.isdigit() for character in value):
            raise ValueError("Phone number must include at least one digit.")
        return value

class ScoredLead(RawLead):
    score: int
    reasoning: str

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
        if value and not any(character.isdigit() for character in value):
            raise ValueError("Phone number must include at least one digit.")
        return value

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
        if value and not any(character.isdigit() for character in value):
            raise ValueError("Phone number must include at least one digit.")
        return value
