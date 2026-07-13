from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.rate_limiter import limiter
from app.controllers.dashboard_controller import DashboardController
from app.schemas.dashboard_schema import UsageFilterSchema

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/credit-usage")
@limiter.limit("20/minute")
async def get_credit_usage_analytics(
    request: Request,
    filters: UsageFilterSchema = Depends(),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve dynamic Token/Credit Usage Analytics.
    Use this endpoint to populate dashboard charts showing how many credits/tokens
    an organization is consuming over time. Supports filtering by date range,
    operation type (e.g. chat, ingestion), and status.
    """
    return await DashboardController.get_credit_usage_analytics(filters, db)
