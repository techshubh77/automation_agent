from fastapi import status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.custom_exceptions import AppError
from app.schemas.dashboard_schema import DashboardResponseSchema, UsageFilterSchema
from app.services.dashboard_service import DashboardService
from app.utils.logger import logger
from app.utils.response import success_response


class DashboardController:
    @staticmethod
    async def get_credit_usage_analytics(filters: UsageFilterSchema, db: AsyncSession):
        try:
            analytics = await DashboardService.get_credit_usage_analytics(filters, db)
            formatted_analytics = jsonable_encoder(
                DashboardResponseSchema.model_validate(analytics)
            )
            return success_response(
                message="Token/Credit usage analytics retrieved successfully", data=formatted_analytics
            )
        except AppError:
            raise
        except Exception as e:
            logger.error(f"Error in DashboardController.get_credit_usage_analytics: {e!s}")
            raise AppError(
                "Failed to get token/credit analytics due to an unexpected error",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e
