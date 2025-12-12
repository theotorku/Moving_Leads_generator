from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional
from uuid import UUID

class RawLead(BaseModel):
    full_name: str
    email: str
    phone: str
    move_date: date
    origin_zip: str
    destination_zip: str
    home_size: str
    budget: str
    urgency: str

class ScoredLead(RawLead):
    score: int
    reasoning: str

class Customer(BaseModel):
    id: Optional[UUID] = None
    company_name: str
    email: str
    phone: Optional[str] = None
    stripe_customer_id: Optional[str] = None
    created_at: Optional[datetime] = None

class Subscription(BaseModel):
    id: Optional[UUID] = None
    customer_id: UUID
    tier: str  # 'starter', 'professional', 'enterprise'
    status: str  # 'active', 'canceled', 'past_due'
    leads_included: int
    leads_used: int = 0
    stripe_subscription_id: Optional[str] = None
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    created_at: Optional[datetime] = None

class LeadPurchase(BaseModel):
    id: Optional[UUID] = None
    lead_id: UUID
    customer_id: UUID
    purchase_type: str  # 'included', 'overage'
    price_paid: float
    purchased_at: Optional[datetime] = None