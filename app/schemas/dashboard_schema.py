import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UsageFilterSchema(BaseModel):
    organization_id: str | None = Field(None, description="Organization ID")
    start_date: datetime | None = Field(None, description="Start date")
    end_date: datetime | None = Field(None, description="End date")
    operation_type: str | None = Field(None, description="Operation type")
    status: str | None = Field("completed", description="Status")
    limit: int = Field(10, description="Limit for logs")
    offset: int = Field(0, description="Offset for logs")


class DailyUsageSchema(BaseModel):
    date: str
    credits: float


class UsageSummarySchema(BaseModel):
    total_credits_used: float
    total_operations: int


class UsageLogSchema(BaseModel):
    id: str | uuid.UUID
    operation_type: str
    credits_used: float
    status: str
    cost_breakdown: dict | None = None
    reference_id: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DashboardResponseSchema(BaseModel):
    summary: UsageSummarySchema
    chart_data: list[DailyUsageSchema]
    logs: list[UsageLogSchema]

    model_config = ConfigDict(from_attributes=True)
