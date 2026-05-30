from fastapi import APIRouter, Request

from ..services.webhook_service import process_webhook

router = APIRouter()


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    """Receive Stripe webhook events for billing reconciliation."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    return process_webhook(payload, signature)
