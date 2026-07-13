"""
IngestionService — Document Upload and Job Enqueueing

Handles file validation, duplicate detection, temporary file storage, and
Redis job enqueueing for background document processing.

KEY DESIGN DECISIONS:
  - The duplicate check explicitly EXCLUDES stale/orphaned documents
    (status = 'failed') so users can re-upload a previously failed file.
  - Temp file cleanup always happens in a finally block to prevent disk leaks
    if the Redis enqueue step fails after the file was already written.
  - The "active job" guard includes a staleness check: documents stuck in
    pending/processing beyond STALE_JOB_MINUTES are not considered active.
"""

import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta

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

# A document stuck in pending/processing beyond this many minutes is considered
# orphaned (e.g., worker was killed mid-job). It is automatically treated as
# non-blocking and eligible for re-upload.
STALE_JOB_MINUTES = 30

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
    async def _save_or_update_document(
        cls, db: AsyncSession, file: UploadFile, existing_doc: Document | None, file_config: dict, file_hash: str, organization_id: str | None, source_type: SourceType | None, module: str | None
    ) -> str:
        if existing_doc:
            # Overwrite path: reuse existing UUID, reset status to pending
            existing_doc.status = "pending"
            existing_doc.filename = file.filename
            existing_doc.file_type = file_config["label"]
            existing_doc.file_hash = file_hash
            existing_doc.error_message = None
            document_id_str = str(existing_doc.id)
            await db.commit()
            logger.info("Updated existing document {} — reset to pending for re-ingestion.", document_id_str)
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
            logger.info("Created new document record {} in pending state.", document_id_str)
        return document_id_str

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
        logger.info("Enqueuing ingestion process for file: {}", file.filename)

        # ── Active Job Guard ──────────────────────────────────────────────────
        # Block if a genuinely active job exists for this org.
        # Documents stuck beyond STALE_JOB_MINUTES are considered orphaned and
        # do NOT block new uploads. They will be cleaned up below.
        if organization_id:
            stale_cutoff = datetime.now(UTC) - timedelta(minutes=STALE_JOB_MINUTES)
            active_jobs_query = select(Document).where(
                Document.organization_id == organization_id,
                Document.status.in_(["pending", "processing"]),
                Document.updated_at > stale_cutoff,  # Only block if recently updated
            )
            active_jobs_result = await db.execute(active_jobs_query)
            if active_jobs_result.scalars().first():
                raise AppError(
                    "An upload is currently in progress. Please wait for it to complete before uploading another file.",
                    status.HTTP_409_CONFLICT,
                )

            # Auto-recover stale orphaned documents for this org
            await cls._recover_stale_documents(db, organization_id, stale_cutoff)

        # 1. Validate source_type and file type
        file_config, file_extension = cls._validate_file(file, source_type)

        # 2. Read and validate file bytes
        file_bytes = await file.read()
        if len(file_bytes) == 0:
            raise AppError("Uploaded file is empty.", status.HTTP_400_BAD_REQUEST)
        if len(file_bytes) > MAX_FILE_SIZE:
            raise AppError(
                "File size exceeds the 10MB limit.",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # 3. Hash file for duplicate detection
        file_hash = hashlib.sha256(file_bytes).hexdigest()
        existing_doc = await cls._check_database_for_duplicates(
            db, organization_id, module, file_hash
        )

        # 4. Write file to shared storage
        temp_dir = "shared_storage"
        os.makedirs(temp_dir, exist_ok=True)
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        temp_filepath = os.path.join(temp_dir, unique_filename)

        # Write first — if DB or Redis ops fail, we clean up in the finally block
        async with aiofiles.open(temp_filepath, "wb") as f:
            await f.write(file_bytes)

        try:
            # 5. Create or update the Document record
            document_id_str = await cls._save_or_update_document(
                db, file, existing_doc, file_config, file_hash, organization_id, source_type, module
            )

            # 6. Enqueue job to Redis broker
            # If this fails, the DB is already committed with "pending" status.
            # The finally block will clean up the temp file.
            job_id_str = f"{document_id_str}_{uuid.uuid4().hex[:8]}"
            job = await redis_pool.enqueue_job(
                "ingest_document_job",
                doc_id=document_id_str,
                filepath=temp_filepath,
                _job_id=job_id_str,  # Unique ID per retry to bypass arq cache
            )
            if job is None:
                raise RuntimeError(f"arq returned None for job ID {job_id_str}")

            logger.info("Job successfully enqueued to Redis with Job ID: {}", job_id_str)

            return {"document_id": document_id_str, "status": "pending"}

        except AppError:
            raise
        except Exception as e:
            # If Redis enqueue failed, the document is committed as "pending"
            # but no worker will ever pick it up. Clean up the temp file and
            # reset the document status to "failed" so the user can retry.
            logger.error(
                "Failed to enqueue ingestion job for document. Rolling back. Error: {}", str(e)
            )
            try:
                # Rollback the "pending" commit and mark as failed
                await db.rollback()
                # Re-fetch and set to failed in a new clean operation
                if existing_doc:
                    existing_doc.status = "failed"
                    existing_doc.error_message = f"Failed to queue background job: {e!s}"
                    await db.commit()
            except Exception:
                pass  # Best effort — temp file cleanup in finally handles the rest
            raise AppError(
                "Failed to queue the upload for processing. Please try again.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e
        finally:
            # IMPORTANT: If Redis enqueue fails, clean up the orphaned temp file.
            # On success, the worker is responsible for cleanup after processing.
            if "document_id_str" not in locals() and os.path.exists(temp_filepath):
                os.remove(temp_filepath)
                logger.info("Cleaned up temp file after failed enqueue: {}", temp_filepath)

    @staticmethod
    async def _recover_stale_documents(
        db: AsyncSession, organization_id: str, stale_cutoff: datetime
    ) -> None:
        """
        Auto-recovers orphaned documents stuck in pending/processing beyond
        the stale cutoff time. Marks them as 'failed' so users can re-upload.

        This handles documents left behind when the worker process was killed
        (e.g., Docker restart, SIGKILL) mid-processing.
        """
        stale_query = select(Document).where(
            Document.organization_id == organization_id,
            Document.status.in_(["pending", "processing"]),
            Document.updated_at <= stale_cutoff,
        )
        stale_result = await db.execute(stale_query)
        stale_docs = stale_result.scalars().all()

        if stale_docs:
            logger.warning(
                "Found {} stale document(s) for org '{}'. Auto-recovering to 'failed' status.",
                len(stale_docs),
                organization_id,
            )
            for doc in stale_docs:
                doc.status = "failed"
                doc.error_message = (
                    f"Job timed out after {STALE_JOB_MINUTES} minutes. "
                    "The worker may have been restarted. Please re-upload the file."
                )
            await db.commit()

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
            logger.warning("Unsupported file type uploaded: {}", file.filename)
            raise AppError(
                f"Unsupported file type. Accepted formats: {list(SUPPORTED_FILE_TYPES.keys())}",
                status.HTTP_400_BAD_REQUEST,
            )

        file_config = SUPPORTED_FILE_TYPES[file_extension]

        if file.content_type != file_config["mime"]:
            logger.warning(
                "MIME type mismatch for {}: expected {}, got {}",
                file.filename,
                file_config["mime"],
                file.content_type,
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
        """
        Checks for duplicate files and returns an existing doc slot to overwrite.

        IMPORTANT: Only 'completed' documents are considered true duplicates.
        Documents in 'failed', 'pending', or 'processing' status are NOT treated
        as active duplicates — they are dead/orphaned jobs and the user should be
        able to re-upload to retry processing.
        """
        # Check for exact content duplicate among COMPLETED documents only
        dup_query = select(Document).where(
            Document.file_hash == file_hash,
            Document.status == "completed",  # Only completed docs are real duplicates
        )
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

        # Check for an existing file in the same slot (module + org) to overwrite.
        # This covers both completed and failed docs — re-uploading replaces the slot.
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
                    "Found existing document (ID: {}, status: {}). Will overwrite.",
                    existing_doc.id,
                    existing_doc.status,
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

        for i, chunk in enumerate(chunks):
            chunk_unique_name = f"{document_id_str}_chunk_{i}"
            deterministic_uuid = uuid.uuid5(CHUNK_NAMESPACE, chunk_unique_name)
            point_ids.append(str(deterministic_uuid))
            payloads.append(
                {
                    "metadata": {
                        "document_id": document_id_str,
                        "organization_id": organization_id,
                        "source_type": source_type.value if source_type else None,
                        "module": module,
                        "chunk_index": i,
                    },
                    "page_content": chunk,
                }
            )

        await VectorStore.upsert_chunks(ids=point_ids, vectors=vectors, payloads=payloads)
        logger.info("Successfully upserted chunks to Qdrant.")
