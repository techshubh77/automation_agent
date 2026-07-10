import hashlib
import os
import uuid

import aiofiles
from fastapi import UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.custom_exceptions import AppError
from app.models.document import Document
from app.schemas.source_type_schema import SourceType
from app.services.ai.vector_store import VectorStore
from app.services.ingestion.json_parser import JsonParser
from app.services.ingestion.markdown_parser import MarkdownParser
from app.utils.logger import logger

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
CHUNK_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# A lookup table that maps an accepted file extension to:
SUPPORTED_FILE_TYPES = {
    ".json": {
        "mime": "application/json",
        "parser": JsonParser,
        "label": "json",
    },
    ".md": {
        "mime": "text/markdown",
        "parser": MarkdownParser,
        "label": "markdown",
    },
}


class IngestionService:
    @classmethod
    async def enqueue_file_ingestion(
        cls,
        db: AsyncSession,
        redis_pool,
        file: UploadFile,
        organization_id: str | None = None,
        source_type: SourceType | None = None,
        module: str | None = None,
    ) -> dict:
        logger.info(f"Enqueuing ingestion process for file: {file.filename}")

        if organization_id:
            active_jobs_query = select(Document).where(
                Document.organization_id == organization_id,
                Document.status.in_(["pending", "processing"])
            )
            active_jobs_result = await db.execute(active_jobs_query)
            if active_jobs_result.scalars().first():
                raise AppError(
                    "An upload is currently in progress. Please wait for it to complete before uploading another file.",
                    status.HTTP_409_CONFLICT,
                )

        # 1. Validate source_type and file type
        file_config, file_extension = cls._validate_file(file, source_type)

        # 2. Save temporary upload file
        temp_dir = "shared_storage"
        os.makedirs(temp_dir, exist_ok=True)
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        temp_filepath = os.path.join(temp_dir, unique_filename)

        # Read the file and write to temporary location
        file_bytes = await file.read()

        # Enforce maximum file size
        if len(file_bytes) == 0:
            raise AppError("Uploaded file is empty.", status.HTTP_400_BAD_REQUEST)
        if len(file_bytes) > MAX_FILE_SIZE:
            raise AppError(
                "File size exceeds the 10MB limit.",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # Hash file to check for exact duplicate before enqueuing
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        existing_doc = await cls._check_database_for_duplicates(
            db, organization_id, module, file_hash
        )

        async with aiofiles.open(temp_filepath, "wb") as f:
            await f.write(file_bytes)

        # 3. Create document record in database with "pending" status
        if existing_doc:
            # Overwrite path: update status to pending and reuse existing UUID
            existing_doc.status = "pending"
            existing_doc.filename = file.filename
            existing_doc.file_type = file_config["label"]
            existing_doc.file_hash = file_hash
            document_id_str = str(existing_doc.id)
            await db.commit()
            logger.info(
                f"Updated existing document {document_id_str} status to pending."
            )
        else:
            new_doc = Document(
                organization_id=organization_id,
                filename=file.filename,
                file_hash=file_hash,
                file_type=file_config["label"],
                source_type=source_type,
                module=module,
                status="pending",
            )
            db.add(new_doc)
            await db.flush()
            document_id_str = str(new_doc.id)
            await db.commit()
            logger.info(
                f"Created new document {document_id_str} record in pending state."
            )

        # 4. Enqueue task to Redis broker
        await redis_pool.enqueue_job(
            "ingest_document_job",
            doc_id=document_id_str,
            filepath=temp_filepath,
            _job_id=document_id_str,  # Idempotency using DB UUID
        )
        logger.info(f"Job successfully enqueued to Redis with ID: {document_id_str}")

        return {"document_id": document_id_str, "status": "pending"}

    @staticmethod
    def _validate_file(
        file: UploadFile, source_type: SourceType | None
    ) -> tuple[dict, str]:
        if source_type is None:
            raise AppError(
                f"source_type is required. Allowed values: {[e.value for e in SourceType]}",
                status.HTTP_400_BAD_REQUEST,
            )

        file_extension = None
        for ext in SUPPORTED_FILE_TYPES:
            if file.filename.endswith(ext):
                file_extension = ext
                break

        if file_extension is None:
            logger.warning(f"Unsupported file type uploaded: {file.filename}")
            raise AppError(
                f"Unsupported file type. Accepted formats: {list(SUPPORTED_FILE_TYPES.keys())}",
                status.HTTP_400_BAD_REQUEST,
            )

        file_config = SUPPORTED_FILE_TYPES[file_extension]

        if file.content_type != file_config["mime"]:
            logger.warning(
                f"MIME type mismatch for {file.filename}: "
                f"expected {file_config['mime']}, got {file.content_type}"
            )
            raise AppError(
                f"Invalid Content-Type for a {file_extension} file. "
                f"Expected: {file_config['mime']}",
                status.HTTP_400_BAD_REQUEST,
            )

        return file_config, file_extension

    @staticmethod
    async def _check_database_for_duplicates(
        db: AsyncSession,
        organization_id: str | None,
        module: str | None,
        file_hash: str,
    ) -> Document | None:
        # 1. Exact Duplicate Check (checks same file content)
        dup_query = select(Document).where(Document.file_hash == file_hash)
        if organization_id:
            dup_query = dup_query.where(Document.organization_id == organization_id)
        if module:
            dup_query = dup_query.where(Document.module == module)

        exact_duplicate = await db.execute(dup_query)
        if exact_duplicate.scalars().first():
            raise AppError(
                "This exact file is already active in this module.",
                status.HTTP_409_CONFLICT,
            )

        # 2. Existing File check for Overwrite (checks if a file exists in the slot to replace it)
        # We only overwrite if a specific slot (module + org, or at least module) is targeted
        if module:
            existing_query = select(Document).where(Document.module == module)
            if organization_id:
                existing_query = existing_query.where(
                    Document.organization_id == organization_id
                )

            existing_result = await db.execute(existing_query)
            existing_doc = existing_result.scalars().first()
            if existing_doc:
                logger.info(
                    f"Found existing document (ID: {existing_doc.id}). Will overwrite in background."
                )
            return existing_doc

        return None

    @staticmethod
    async def _upsert_to_qdrant(
        chunks: list[str],
        vectors: list[list[float]],
        document_id_str: str,
        organization_id: str | None,
        source_type: SourceType | None,
        module: str | None,
    ):
        logger.info(
            "Upserting embedded vectors to Qdrant Vector Store using deterministic IDs..."
        )

        point_ids = []
        payloads = []

        # Loop through each chunk one by one
        for i, chunk in enumerate(chunks):
            # 1. Calculate the deterministic ID for this specific chunk
            chunk_unique_name = f"{document_id_str}_chunk_{i}"
            deterministic_uuid = uuid.uuid5(CHUNK_NAMESPACE, chunk_unique_name)

            point_ids.append(str(deterministic_uuid))

            # 2. Build the metadata and payload for this chunk
            chunk_metadata = {
                "document_id": document_id_str,
                "organization_id": organization_id,
                "source_type": source_type.value if source_type else None,
                "module": module,
                "chunk_index": i,
            }

            payload = {
                "metadata": chunk_metadata,
                "page_content": chunk,
            }

            payloads.append(payload)
        await VectorStore.upsert_chunks(
            ids=point_ids, vectors=vectors, payloads=payloads
        )
        logger.info("Successfully upserted chunks to Qdrant.")
