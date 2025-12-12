import os
import stripe
from dotenv import load_dotenv

load_dotenv()

stripe_key = os.getenv("STRIPE_SECRET_KEY")
if not stripe_key:
    print("WARNING: STRIPE_SECRET_KEY not found in environment variables!")
    print("Customer registration will fail. Please add STRIPE_SECRET_KEY to your .env file.")
else:
    stripe.api_key = stripe_key
    print(f"✅ Stripe initialized with key: {stripe_key[:7]}...")

# Pricing tiers configuration
PRICING_TIERS = {
    "starter": {
        "price": 299,
        "leads_included": 30,
        "overage_price": 12
    },
    "professional": {
        "price": 599,
        "leads_included": 75,
        "overage_price": 10
    },
    "enterprise": {
        "price": 999,
        "leads_included": 150,
        "overage_price": 8
    }
}

async def create_customer(email: str, company_name: str) -> dict:
    """Create a Stripe customer"""
    try:
        customer = stripe.Customer.create(
            email=email,
            name=company_name,
            metadata={"company_name": company_name}
        )
        return {"stripe_customer_id": customer.id, "success": True}
    except Exception as e:
        print(f"Stripe customer creation error: {e}")
        return {"success": False, "error": str(e)}

async def create_subscription(customer_id: str, tier: str) -> dict:
    """Create a Stripe subscription for a customer"""
    if tier not in PRICING_TIERS:
        return {"success": False, "error": "Invalid tier"}
    
    try:
        # In production, you'd create a Stripe Price/Product first
        # For now, we'll use a simple subscription without a product
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"{tier.capitalize()} Plan"
                    },
                    "unit_amount": PRICING_TIERS[tier]["price"] * 100,  # Stripe uses cents
                    "recurring": {"interval": "month"}
                }
            }],
            metadata={
                "tier": tier,
                "leads_included": PRICING_TIERS[tier]["leads_included"]
            }
        )
        return {
            "success": True,
            "subscription_id": subscription.id,
            "status": subscription.status
        }
    except Exception as e:
        print(f"Stripe subscription creation error: {e}")
        return {"success": False, "error": str(e)}

async def charge_overage(customer_id: str, num_leads: int, tier: str) -> dict:
    """Charge for overage leads"""
    if tier not in PRICING_TIERS:
        return {"success": False, "error": "Invalid tier"}
    
    amount = num_leads * PRICING_TIERS[tier]["overage_price"]
    
    try:
        charge = stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Convert to cents
            currency="usd",
            customer=customer_id,
            description=f"Overage charge for {num_leads} leads",
            metadata={"type": "overage", "num_leads": num_leads}
        )
        return {"success": True, "charge_id": charge.id, "amount": amount}
    except Exception as e:
        print(f"Stripe overage charge error: {e}")
        return {"success": False, "error": str(e)}
