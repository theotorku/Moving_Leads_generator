from fastapi import APIRouter

from ..models import CustomerRegistration
from ..services.customer_service import (
    get_customer_record,
    get_customer_usage_summary,
    register_customer_with_subscription,
)

router = APIRouter()

@router.post("/customers/register")
async def register_customer(registration: CustomerRegistration):
    """Register a new customer and create their subscription"""
    return await register_customer_with_subscription(registration)

@router.get("/customers/{customer_id}")
async def get_customer(customer_id: str):
    """Get customer details"""
    return get_customer_record(customer_id)

@router.get("/customers/{customer_id}/usage")
async def get_customer_usage(customer_id: str):
    """Get customer's lead usage statistics"""
    return get_customer_usage_summary(customer_id)
