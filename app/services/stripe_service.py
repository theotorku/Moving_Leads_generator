import logging

import stripe

from ..config import get_settings

logger = logging.getLogger(__name__)

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
        settings = get_settings()
        if not settings.stripe_secret_key:
            logger.warning("Stripe customer creation requested without STRIPE_SECRET_KEY configured.")
            return {"success": False, "error": "Payment provider is not configured."}

        stripe.api_key = settings.stripe_secret_key.get_secret_value()
        customer = stripe.Customer.create(
            email=email,
            name=company_name,
            metadata={"company_name": company_name}
        )
        return {"stripe_customer_id": customer.id, "success": True}
    except stripe.error.StripeError:
        logger.exception("Stripe customer creation failed")
        return {"success": False, "error": "Unable to create the customer in Stripe."}
    except Exception:
        logger.exception("Unexpected Stripe customer creation error")
        return {"success": False, "error": "Unexpected payment provider error."}

async def create_subscription(customer_id: str, tier: str) -> dict:
    """Create a Stripe subscription for a customer"""
    if tier not in PRICING_TIERS:
        return {"success": False, "error": "Invalid tier"}
    
    try:
        settings = get_settings()
        if not settings.stripe_secret_key:
            logger.warning("Stripe subscription creation requested without STRIPE_SECRET_KEY configured.")
            return {"success": False, "error": "Payment provider is not configured."}

        stripe.api_key = settings.stripe_secret_key.get_secret_value()
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
    except stripe.error.StripeError:
        logger.exception("Stripe subscription creation failed")
        return {"success": False, "error": "Unable to create the subscription in Stripe."}
    except Exception:
        logger.exception("Unexpected Stripe subscription creation error")
        return {"success": False, "error": "Unexpected payment provider error."}

async def charge_overage(customer_id: str, num_leads: int, tier: str) -> dict:
    """Charge for overage leads"""
    if tier not in PRICING_TIERS:
        return {"success": False, "error": "Invalid tier"}
    
    amount = num_leads * PRICING_TIERS[tier]["overage_price"]
    
    try:
        settings = get_settings()
        if not settings.stripe_secret_key:
            logger.warning("Stripe overage charge requested without STRIPE_SECRET_KEY configured.")
            return {"success": False, "error": "Payment provider is not configured."}

        stripe.api_key = settings.stripe_secret_key.get_secret_value()
        charge = stripe.PaymentIntent.create(
            amount=int(amount * 100),  # Convert to cents
            currency="usd",
            customer=customer_id,
            description=f"Overage charge for {num_leads} leads",
            metadata={"type": "overage", "num_leads": num_leads}
        )
        return {"success": True, "charge_id": charge.id, "amount": amount}
    except stripe.error.StripeError:
        logger.exception("Stripe overage charge failed")
        return {"success": False, "error": "Unable to charge the overage in Stripe."}
    except Exception:
        logger.exception("Unexpected Stripe overage charge error")
        return {"success": False, "error": "Unexpected payment provider error."}
