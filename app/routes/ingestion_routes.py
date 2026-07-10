from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.rate_limiter import limiter
from app.controllers.ingestion_controller import IngestionController
from app.schemas.source_type_schema import SourceType

# Create the router with the /api/v1/ingestion prefix
router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


@router.post("/document", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("20/hour")
async def ingest_json(
    request: Request,
    file: UploadFile = File(...),
    organization_id: str | None = Form(None),
    source_type: SourceType | None = Form(None),
    module: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    return await IngestionController.ingest_document(
        file=file,
        db=db,
        redis_pool=request.app.state.redis_pool,
        organization_id=organization_id,
        source_type=source_type,
        module=module,
    )
