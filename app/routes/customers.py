from fastapi import APIRouter, HTTPException
from ..models import Customer, Subscription
from ..db import supabase
from ..services.stripe_service import create_customer, create_subscription, PRICING_TIERS
from pydantic import BaseModel

router = APIRouter()

class CustomerRegistration(BaseModel):
    company_name: str
    email: str
    phone: str = None
    tier: str  # 'starter', 'professional', 'enterprise'

@router.post("/customers/register")
async def register_customer(registration: CustomerRegistration):
    """Register a new customer and create their subscription"""
    
    # Validate tier
    if registration.tier not in PRICING_TIERS:
        raise HTTPException(status_code=400, detail="Invalid subscription tier")
    
    # Create Stripe customer
    stripe_result = await create_customer(registration.email, registration.company_name)
    if not stripe_result["success"]:
        raise HTTPException(status_code=500, detail=f"Payment setup failed: {stripe_result.get('error')}")
    
    # Save customer to database
    try:
        customer_data = {
            "company_name": registration.company_name,
            "email": registration.email,
            "phone": registration.phone,
            "stripe_customer_id": stripe_result["stripe_customer_id"]
        }
        
        customer_response = supabase.table("customers").insert(customer_data).execute()
        customer_id = customer_response.data[0]["id"]
        
        # Create Stripe subscription
        sub_result = await create_subscription(
            stripe_result["stripe_customer_id"],
            registration.tier
        )
        
        if not sub_result["success"]:
            raise HTTPException(status_code=500, detail=f"Subscription creation failed: {sub_result.get('error')}")
        
        # Save subscription to database
        subscription_data = {
            "customer_id": customer_id,
            "tier": registration.tier,
            "status": sub_result["status"],
            "leads_included": PRICING_TIERS[registration.tier]["leads_included"],
            "leads_used": 0,
            "stripe_subscription_id": sub_result["subscription_id"]
        }
        
        supabase.table("subscriptions").insert(subscription_data).execute()
        
        return {
            "success": True,
            "customer_id": customer_id,
            "message": f"Successfully registered with {registration.tier} plan"
        }
        
    except Exception as e:
        print(f"Database error: {e}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@router.get("/customers/{customer_id}")
async def get_customer(customer_id: str):
    """Get customer details"""
    try:
        customer = supabase.table("customers").select("*").eq("id", customer_id).execute()
        if not customer.data:
            raise HTTPException(status_code=404, detail="Customer not found")
        return customer.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/customers/{customer_id}/usage")
async def get_customer_usage(customer_id: str):
    """Get customer's lead usage statistics"""
    try:
        subscription = supabase.table("subscriptions")\
            .select("*")\
            .eq("customer_id", customer_id)\
            .eq("status", "active")\
            .execute()
        
        if not subscription.data:
            raise HTTPException(status_code=404, detail="No active subscription found")
        
        sub = subscription.data[0]
        remaining = sub["leads_included"] - sub["leads_used"]
        
        return {
            "tier": sub["tier"],
            "leads_included": sub["leads_included"],
            "leads_used": sub["leads_used"],
            "leads_remaining": remaining,
            "overage_price": PRICING_TIERS[sub["tier"]]["overage_price"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
