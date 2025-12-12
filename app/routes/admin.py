from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from ..db import supabase
from typing import Optional
import secrets
import os

router = APIRouter()
security = HTTPBasic()

# Simple admin authentication (use environment variables in production)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify admin credentials"""
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@router.get("/admin/leads")
async def list_leads(
    status: Optional[str] = None,
    min_score: Optional[int] = None,
    admin: str = Depends(verify_admin)
):
    """List all leads with optional filters"""
    try:
        query = supabase.table("leads").select("*")
        
        if status:
            query = query.eq("status", status)
        if min_score:
            query = query.gte("score", min_score)
        
        result = query.order("created_at", desc=True).execute()
        return {"leads": result.data, "count": len(result.data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/admin/leads/{lead_id}/assign")
async def assign_lead(
    lead_id: str,
    customer_id: str,
    admin: str = Depends(verify_admin)
):
    """Assign a lead to a customer"""
    try:
        # Get customer's active subscription
        subscription = supabase.table("subscriptions")\
            .select("*")\
            .eq("customer_id", customer_id)\
            .eq("status", "active")\
            .execute()
        
        if not subscription.data:
            raise HTTPException(status_code=404, detail="No active subscription found")
        
        sub = subscription.data[0]
        
        # Determine if this is an included lead or overage
        is_overage = sub["leads_used"] >= sub["leads_included"]
        purchase_type = "overage" if is_overage else "included"
        
        # Calculate price
        from ..services.stripe_service import PRICING_TIERS
        price = PRICING_TIERS[sub["tier"]]["overage_price"] if is_overage else 0
        
        # Update lead status
        supabase.table("leads").update({
            "status": "sold",
            "assigned_to": customer_id
        }).eq("id", lead_id).execute()
        
        # Record purchase
        purchase_data = {
            "lead_id": lead_id,
            "customer_id": customer_id,
            "purchase_type": purchase_type,
            "price_paid": price
        }
        supabase.table("lead_purchases").insert(purchase_data).execute()
        
        # Update subscription usage
        supabase.table("subscriptions").update({
            "leads_used": sub["leads_used"] + 1
        }).eq("id", sub["id"]).execute()
        
        return {
            "success": True,
            "purchase_type": purchase_type,
            "price": price,
            "message": f"Lead assigned to customer"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/customers")
async def list_customers(admin: str = Depends(verify_admin)):
    """List all customers with their subscriptions"""
    try:
        customers = supabase.table("customers")\
            .select("*, subscriptions(*)")\
            .execute()
        
        return {"customers": customers.data, "count": len(customers.data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/admin/analytics")
async def get_analytics(admin: str = Depends(verify_admin)):
    """Get revenue and usage analytics"""
    try:
        # Total customers
        customers = supabase.table("customers").select("id").execute()
        total_customers = len(customers.data)
        
        # Active subscriptions
        active_subs = supabase.table("subscriptions")\
            .select("*")\
            .eq("status", "active")\
            .execute()
        
        # Calculate MRR (Monthly Recurring Revenue)
        from ..services.stripe_service import PRICING_TIERS
        mrr = sum(PRICING_TIERS[sub["tier"]]["price"] for sub in active_subs.data)
        
        # Total leads
        leads = supabase.table("leads").select("id, status").execute()
        total_leads = len(leads.data)
        available_leads = len([l for l in leads.data if l.get("status") == "available"])
        sold_leads = len([l for l in leads.data if l.get("status") == "sold"])
        
        # Overage revenue
        purchases = supabase.table("lead_purchases")\
            .select("price_paid")\
            .eq("purchase_type", "overage")\
            .execute()
        overage_revenue = sum(p["price_paid"] for p in purchases.data)
        
        return {
            "total_customers": total_customers,
            "active_subscriptions": len(active_subs.data),
            "monthly_recurring_revenue": mrr,
            "total_leads": total_leads,
            "available_leads": available_leads,
            "sold_leads": sold_leads,
            "overage_revenue": overage_revenue,
            "total_revenue": mrr + overage_revenue
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
