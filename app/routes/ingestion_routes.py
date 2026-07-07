from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.controllers.ingestion_controller import IngestionController
from app.schemas.source_type_schema import SourceType

# Create the router with the /api/v1/ingestion prefix
router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


@router.post("/document")
async def ingest_json(
    file: UploadFile = File(...),
    organization_id: str | None = Form(None),
    project_id: str | None = Form(None),
    source_type: SourceType | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    return await IngestionController.ingest_document(
        file=file,
        db=db,
        organization_id=organization_id,
        project_id=project_id,
        source_type=source_type,
    )
