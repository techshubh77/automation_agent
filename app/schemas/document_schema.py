from pydantic import BaseModel


class IngestionMetadata(BaseModel):
    organization_id: str | None = None
    project_id: str | None = None
    source_type: str | None = None

    # You can accept any additional unstructured metadata here
    meta_data: dict | None = None
