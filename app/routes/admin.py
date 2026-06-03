import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ..config import get_settings
from ..models import LeadStatus, RoutingProfileUpdate
from ..services.admin_service import (
    assign_lead_to_customer,
    get_admin_analytics,
    get_conversion_analytics,
    get_lead_sources,
    get_routing_profile,
    list_lead_assignment_options,
    list_customers_for_admin,
    list_leads_for_admin,
    record_lead_outcome,
    upsert_routing_profile,
)

router = APIRouter()
security = HTTPBasic()
logger = logging.getLogger(__name__)

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials"""
    settings = get_settings()
    correct_username = secrets.compare_digest(credentials.username, settings.admin_username)
    correct_password = secrets.compare_digest(
        credentials.password,
        settings.admin_password.get_secret_value(),
    )
    
    if not (correct_username and correct_password):
        logger.warning("Rejected admin authentication attempt for username '%s'", credentials.username)
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@router.get("/admin/leads")
async def list_leads(
    status: Optional[LeadStatus] = None,
    min_score: Optional[int] = Query(default=None, ge=0, le=100),
    admin: str = Depends(verify_admin)
):
    """List all leads with optional filters"""
    return list_leads_for_admin(status=status, min_score=min_score)

@router.post("/admin/leads/{lead_id}/assign")
async def assign_lead(
    lead_id: str,
    customer_id: str,
    admin: str = Depends(verify_admin)
):
    """Assign a lead to a customer"""
    return await assign_lead_to_customer(lead_id=lead_id, customer_id=customer_id)


@router.get("/admin/leads/{lead_id}/assignment-options")
async def get_assignment_options(
    lead_id: str,
    admin: str = Depends(verify_admin)
):
    """List the safest customer assignment options for a lead."""
    return list_lead_assignment_options(lead_id=lead_id)

@router.get("/admin/customers")
async def list_customers(admin: str = Depends(verify_admin)):
    """List all customers with their subscriptions"""
    return list_customers_for_admin()

@router.get("/admin/customers/{customer_id}/routing-profile")
async def read_routing_profile(customer_id: str, admin: str = Depends(verify_admin)):
    """Get a customer's lead-routing profile."""
    return get_routing_profile(customer_id)

@router.put("/admin/customers/{customer_id}/routing-profile")
async def write_routing_profile(
    customer_id: str,
    profile: RoutingProfileUpdate,
    admin: str = Depends(verify_admin),
):
    """Create/update a customer's lead-routing profile."""
    return upsert_routing_profile(customer_id, profile.model_dump())

@router.get("/admin/analytics")
async def get_analytics(admin: str = Depends(verify_admin)):
    """Get revenue and usage analytics"""
    return get_admin_analytics()

@router.get("/admin/conversion")
async def get_conversion(admin: str = Depends(verify_admin)):
    """Get the sold->booked funnel and cost per booked move."""
    return get_conversion_analytics()

@router.get("/admin/sources")
async def get_sources(admin: str = Depends(verify_admin)):
    """Per-channel acquisition rollup — where leads come from (volume/quality/conversion)."""
    return {"sources": get_lead_sources()}

@router.post("/admin/purchases/{purchase_id}/outcome")
async def set_purchase_outcome(
    purchase_id: str,
    outcome: str,
    booked_revenue: Optional[float] = Query(default=None, ge=0),
    dispute_reason: Optional[str] = None,
    admin: str = Depends(verify_admin),
):
    """Record the outcome of a sold lead (the feedback loop)."""
    return record_lead_outcome(
        purchase_id=purchase_id,
        outcome=outcome,
        booked_revenue=booked_revenue,
        dispute_reason=dispute_reason,
    )
