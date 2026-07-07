from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.custom_exceptions import AppError
from app.schemas.source_type_schema import SourceType
from app.services.ingestion_service import IngestionService
from app.utils.logger import logger
from app.utils.response import success_response


class IngestionController:
    @staticmethod
    async def ingest_document(
        file: UploadFile,
        db: AsyncSession,
        organization_id: str | None = None,
        project_id: str | None = None,
        source_type: SourceType | None = None,
    ):
        try:
            result = await IngestionService.ingest_document(
                db=db,
                file=file,
                organization_id=organization_id,
                project_id=project_id,
                source_type=source_type,
            )

            return success_response(
                message="File ingested successfully", data=result, status_code=200
            )
        except AppError:
            # Already a clean app error, let the global handler manage it
            raise
        except Exception as e:
            logger.error(f"Error in IngestionController.ingest_json: {e!s}")
            raise AppError(
                "Failed to ingest document due to an unexpected error", 500
            ) from e
