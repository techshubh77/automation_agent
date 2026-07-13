from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credit_usage import CreditUsage
from app.schemas.dashboard_schema import UsageFilterSchema


class DashboardService:
    @staticmethod
    async def get_credit_usage_analytics(filters: UsageFilterSchema, db: AsyncSession):
        """
        Retrieves aggregated Token/Credit Usage analytics for the dashboard.
        Calculates both total totals and daily time-series data.
        """
        conditions = []
        if filters.organization_id:
            conditions.append(CreditUsage.organization_id == filters.organization_id)
        if filters.start_date:
            conditions.append(CreditUsage.created_at >= filters.start_date)
        if filters.end_date:
            conditions.append(CreditUsage.created_at <= filters.end_date)
        if filters.operation_type:
            conditions.append(CreditUsage.operation_type == filters.operation_type)
        if filters.status:
            conditions.append(CreditUsage.status == filters.status)

        where_clause = and_(*conditions) if conditions else True

        # Total Aggregates
        total_stmt = select(
            func.coalesce(func.sum(CreditUsage.credits_used), 0).label("total_credits"),
            func.count(CreditUsage.id).label("total_operations")
        ).where(where_clause)

        total_result = await db.execute(total_stmt)
        totals = total_result.first()

        # Time-Series (Daily Chart Data)
        chart_stmt = select(
            func.date_trunc('day', CreditUsage.created_at).label("day"),
            func.coalesce(func.sum(CreditUsage.credits_used), 0).label("daily_credits")
        ).where(where_clause).group_by("day").order_by("day")

        chart_result = await db.execute(chart_stmt)
        chart_data = [{"date": row.day.strftime("%Y-%m-%d"), "credits": row.daily_credits} for row in chart_result]

        # Individual Paginated Logs
        logs_stmt = select(CreditUsage).where(where_clause).order_by(CreditUsage.created_at.desc()).limit(filters.limit).offset(filters.offset)
        logs_result = await db.execute(logs_stmt)
        logs_data = logs_result.scalars().all()

        return {
            "summary": {
                "total_credits_used": totals.total_credits if totals else 0,
                "total_operations": totals.total_operations if totals else 0
            },
            "chart_data": chart_data,
            "logs": logs_data
        }
