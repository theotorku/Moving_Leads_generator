import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from ..config import get_settings
from ..models import ChannelCostUpdate, IngestSourceCreate, LeadStatus, RoutingProfileUpdate
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
    set_channel_cost,
    upsert_routing_profile,
)
from ..services.audit_service import list_admin_audit, record_admin_action
from ..services.csv_import import import_leads_from_csv
from ..services.ingest_service import (
    create_ingest_source,
    list_ingest_sources,
    revoke_ingest_source,
)
from ..services.rate_limit import FixedWindowRateLimiter, client_ip

router = APIRouter()
security = HTTPBasic()
logger = logging.getLogger(__name__)

# Brute-force throttle: only *failed* admin logins consume budget (a correct
# credential is never throttled), so normal dashboard polling is unaffected.
_login_limiter = FixedWindowRateLimiter(get_settings().admin_login_max_attempts_per_minute)


def verify_admin(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials, with a per-IP lockout on repeated failures."""
    settings = get_settings()
    correct_username = secrets.compare_digest(credentials.username, settings.admin_username)
    correct_password = secrets.compare_digest(
        credentials.password,
        settings.admin_password.get_secret_value(),
    )
    if correct_username and correct_password:
        return credentials.username

    # Failed: charge this IP's attempt budget; lock out once it's exhausted.
    ip = client_ip(request)
    if not _login_limiter.allow(ip):
        logger.warning("Admin login locked out for IP %s (too many failures)", ip)
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again in a minute.",
            headers={"WWW-Authenticate": "Basic"},
        )
    logger.warning("Rejected admin authentication attempt for username '%s'", credentials.username)
    raise HTTPException(
        status_code=401,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Basic"},
    )


def make_auditor(request: Request, admin: str = Depends(verify_admin)):
    """Auth + an audit logger bound to this admin user and request IP.

    Returns a callable: audit(action, target_type=None, target_id=None, detail=None).
    """
    ip = client_ip(request)

    def _audit(action, target_type=None, target_id=None, detail=None):
        record_admin_action(
            admin_user=admin, action=action, target_type=target_type,
            target_id=target_id, detail=detail, ip=ip,
        )

    _audit.admin = admin
    return _audit

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
    audit=Depends(make_auditor),
):
    """Assign a lead to a customer"""
    result = await assign_lead_to_customer(lead_id=lead_id, customer_id=customer_id)
    audit("assign_lead", target_type="lead", target_id=lead_id, detail={"customer_id": customer_id})
    return result


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
    audit=Depends(make_auditor),
):
    """Create/update a customer's lead-routing profile."""
    result = upsert_routing_profile(customer_id, profile.model_dump())
    audit("update_routing_profile", target_type="customer", target_id=customer_id, detail=profile.model_dump())
    return result

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
    """Per-channel acquisition rollup — where leads come from (volume/quality/conversion/ROI)."""
    return {"sources": get_lead_sources()}

@router.put("/admin/sources/{channel}/cost")
async def set_source_cost(channel: str, body: ChannelCostUpdate, audit=Depends(make_auditor)):
    """Set a channel's acquisition cost-per-lead (drives spend / ROI / cost-per-booked)."""
    result = set_channel_cost(channel, body.cost_per_lead)
    audit("set_channel_cost", target_type="channel", target_id=channel, detail={"cost_per_lead": body.cost_per_lead})
    return result

@router.get("/admin/audit")
async def get_audit(limit: int = Query(default=100, ge=1, le=500), admin: str = Depends(verify_admin)):
    """Recent mutating admin actions (who/action/target/ip/time)."""
    return {"entries": list_admin_audit(limit=limit)}

@router.get("/admin/ingest-sources")
async def list_intake_sources(admin: str = Depends(verify_admin)):
    """List partner intake sources (no keys — those are shown once at creation)."""
    return {"ingest_sources": list_ingest_sources()}

@router.post("/admin/ingest-sources", status_code=201)
async def create_intake_source(body: IngestSourceCreate, audit=Depends(make_auditor)):
    """Create a partner intake source; returns the API key ONCE (store it now)."""
    result = create_ingest_source(label=body.label, channel=body.channel, partner=body.partner)
    audit("create_ingest_source", target_type="ingest_source", target_id=result.get("id"),
          detail={"slug": result.get("slug"), "channel": result.get("channel")})
    return result

@router.post("/admin/ingest-sources/{source_id}/revoke")
async def revoke_intake_source(source_id: str, audit=Depends(make_auditor)):
    """Deactivate a partner key so it can no longer submit leads."""
    result = revoke_ingest_source(source_id)
    audit("revoke_ingest_source", target_type="ingest_source", target_id=source_id)
    return result

@router.post("/admin/leads/import")
async def import_leads(
    file: UploadFile = File(...),
    channel: str = Form("manual"),
    audit=Depends(make_auditor),
):
    """Bulk-import leads from an uploaded CSV (scored + persisted per row)."""
    raw = await file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded CSV.") from exc
    result = await import_leads_from_csv(content, channel=channel)
    audit("import_leads_csv", target_type="channel", target_id=result.get("channel"),
          detail={"imported": result.get("imported"), "total_rows": result.get("total_rows")})
    return result

@router.post("/admin/purchases/{purchase_id}/outcome")
async def set_purchase_outcome(
    purchase_id: str,
    outcome: str,
    booked_revenue: Optional[float] = Query(default=None, ge=0),
    dispute_reason: Optional[str] = None,
    audit=Depends(make_auditor),
):
    """Record the outcome of a sold lead (the feedback loop)."""
    result = record_lead_outcome(
        purchase_id=purchase_id,
        outcome=outcome,
        booked_revenue=booked_revenue,
        dispute_reason=dispute_reason,
    )
    audit("record_outcome", target_type="purchase", target_id=purchase_id,
          detail={"outcome": outcome, "booked_revenue": booked_revenue})
    return result
