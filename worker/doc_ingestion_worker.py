"""
Document Ingestion Worker (arq background job)

This worker runs as a separate process and processes file ingestion jobs
enqueued by IngestionService.enqueue_file_ingestion().

HOW ORPHANED DOCUMENTS ARE PREVENTED:
  1. All job logic is wrapped in asyncio.wait_for(timeout=JOB_TIMEOUT_SECONDS).
     If the job takes too long, asyncio.TimeoutError is caught and the document
     is explicitly set to "failed" — arq cannot silently kill the job anymore.

  2. The error handler uses a fresh database session (not the rolled-back one).
     The original session is rolled back and closed; a brand new session commits
     the "failed" status. This prevents the #1 cause of stuck "processing" docs.

  3. WorkerSettings.max_tries = 1: arq will never automatically retry a failed
     job. Re-tries must be explicitly triggered by re-uploading the file.
"""

import asyncio
import hashlib
import json
import os
import uuid

import aiofiles
from sqlalchemy import select, update

from app.config.database import AsyncSessionLocal
from app.config.redis import redis_settings
from app.models.document import Document
from app.models.organization import Organization
from app.services.ai.embedder import Embedder
from app.services.ai.vector_store import VectorStore
from app.services.ingestion.chunker import TextChunker
from app.services.ingestion_service import CHUNK_NAMESPACE, SUPPORTED_FILE_TYPES
from app.utils.email_helper import send_ingestion_alert
from app.utils.logger import logger
from app.models.credit_usage import CreditUsage
from app.services.pricing_engine import PricingEngine
from app.config.settings import settings

# Maximum time allowed for one full ingestion job (parsing + embedding + vector upsert).
# If exceeded, asyncio.TimeoutError is caught, and the document is marked "failed".
# Set conservatively to handle large files on slower OpenAI embedding responses.
JOB_TIMEOUT_SECONDS = 600  # 10 minutes


async def _mark_document_failed(doc_id: str, filepath: str, error: str) -> None:
    """
    Opens a FRESH database session (independent of any rolled-back session)
    and sets the document status to "failed".

    WHY A FRESH SESSION:
    After a db.rollback(), SQLAlchemy's session identity map may be inconsistent.
    Reusing the same session to re-fetch and update can silently fail or raise
    IntegrityErrors. Opening a new session guarantees a clean state.
    """
    logger.info("[Worker] Opening fresh session to mark document '{}' as failed.", doc_id)
    try:
        async with AsyncSessionLocal() as recovery_db:
            failed_doc = await recovery_db.get(Document, uuid.UUID(doc_id))
            if failed_doc:
                failed_doc.status = "failed"
                failed_doc.error_message = error[:2000]  # Truncate to fit DB column
                await recovery_db.commit()
                logger.info("[Worker] Document '{}' marked as failed.", doc_id)

                # Send failure email notification
                if failed_doc.organization_id:
                    org_result = await recovery_db.execute(
                        select(Organization).where(
                            Organization.organization_id == failed_doc.organization_id
                        )
                    )
                    org = org_result.scalars().first()
                    if org and org.email:
                        await send_ingestion_alert(
                            doc_id,
                            failed_doc.filename,
                            "failed",
                            to_email=org.email,
                        )
    except Exception as recovery_err:
        # If even the recovery fails, log it loudly — a human must intervene.
        logger.critical(
            "[Worker] CRITICAL: Could not mark document '%s' as failed. "
            "Manual DB intervention required. Error: %s",
            doc_id,
            str(recovery_err),
        )
    finally:
        # Always clean up the temp file regardless of DB recovery success
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
            logger.info("[Worker] Cleaned up temporary file: {}", filepath)


async def _run_ingestion(ctx, doc_id: str, filepath: str) -> None:
    """
    Core ingestion logic. Called by ingest_document_job inside asyncio.wait_for().
    Any exception here will be caught by the outer handler.
    """
    async with AsyncSessionLocal() as db:
        try:
            # 1. Fetch document record and mark as processing
            doc = await db.get(Document, uuid.UUID(doc_id))
            if not doc:
                logger.error("[Worker] Document {} not found in database.", doc_id)
                return

            doc.status = "processing"
            await db.commit()

            # Fetch organization email for notifications
            org_email = None
            if doc.organization_id:
                org_result = await db.execute(
                    select(Organization).where(
                        Organization.organization_id == doc.organization_id
                    )
                )
                org = org_result.scalars().first()
                if org and org.email:
                    org_email = org.email

            # 2. Read file from shared storage
            if not os.path.exists(filepath):
                raise FileNotFoundError(
                    f"[Worker] File not found on shared storage: {filepath}"
                )

            async with aiofiles.open(filepath, "rb") as f:
                file_bytes = await f.read()

            file_hash = hashlib.sha256(file_bytes).hexdigest()

            # 3. Select the correct parser for this file type
            file_extension = None
            parser = None
            for ext, config in SUPPORTED_FILE_TYPES.items():
                if config["label"] == doc.file_type:
                    file_extension = ext
                    parser = config["parser"]
                    break

            if not file_extension or parser is None:
                raise ValueError(
                    f"[Worker] Unsupported document file type label: {doc.file_type}"
                )

            parsed_data = parser.parse_file_content(file_bytes)
            
            # 4. Chunk and Embed
            chunks = []
            texts_to_embed = []
            
            if isinstance(parsed_data, list):
                # JSON Parser path
                logger.info("[Worker] File parsed successfully. Objects: %d", len(parsed_data))
                for item in parsed_data:
                    # Dump the JSON object to a string for storage in page_content
                    chunks.append(json.dumps(item))
                    # Extract embedding text (fallback to description or name, then full dump)
                    emb_text = item.get("embedding_text") or item.get("description") or item.get("name") or json.dumps(item)
                    texts_to_embed.append(emb_text)
            else:
                # Markdown Parser path
                logger.info("[Worker] File parsed successfully. Characters: %d", len(parsed_data))
                chunks = TextChunker.chunk_text(parsed_data)
                texts_to_embed = chunks
            
            logger.info("[Worker] Generated {} chunks.", len(chunks))

            vectors = []
            tokens = 0
            if texts_to_embed:
                logger.info(
                    "[Worker] Requesting embeddings from OpenAI for %d chunks...", len(texts_to_embed)
                )
                vectors, tokens = await Embedder.embed_documents(texts_to_embed)

            # 5. Delete old vectors for this document before upserting new ones.
            # This prevents orphaned vectors when a file is re-uploaded.
            logger.info("[Worker] Deleting old vectors for document {}...", doc_id)
            await VectorStore.delete_by_document_id(doc_id)

            # 6. Upsert fresh vectors to Qdrant
            if chunks and vectors:
                point_ids = []
                payloads = []
                for i, chunk in enumerate(chunks):
                    chunk_unique_name = f"{doc_id}_chunk_{i}"
                    deterministic_uuid = uuid.uuid5(CHUNK_NAMESPACE, chunk_unique_name)
                    point_ids.append(str(deterministic_uuid))
                    payloads.append(
                        {
                            "metadata": {
                                "document_id": doc_id,
                                "organization_id": doc.organization_id,
                                "source_type": doc.source_type,
                                "module": doc.module,
                                "chunk_index": i,
                            },
                            "page_content": chunk,
                        }
                    )

                logger.info("[Worker] Upserting fresh vectors to Qdrant...")
                await VectorStore.upsert_chunks(ids=point_ids, vectors=vectors, payloads=payloads)

            # 7. Mark document as completed
            doc.file_hash = file_hash
            doc.status = "completed"
            doc.error_message = None

            # 8. Bill the organization
            if tokens > 0 and doc.organization_id:
                cost_breakdown = PricingEngine.calculate(
                    provider="openai",
                    model=settings.openai_embedding_model,
                    input_tokens=tokens,
                    output_tokens=0,
                    organization_id=doc.organization_id,
                    reference_id=doc_id
                )
                
                usage_log = CreditUsage(
                    organization_id=doc.organization_id,
                    operation_type="ingestion",
                    credits_used=cost_breakdown.credits_used,
                    cost_breakdown=cost_breakdown.model_dump(mode="json"),
                    reference_id=doc_id,
                    status="completed"
                )
                db.add(usage_log)

                stmt = (
                    update(Organization)
                    .where(Organization.organization_id == doc.organization_id)
                    .values(credit_balance=Organization.credit_balance - cost_breakdown.credits_used)
                )
                await db.execute(stmt)

            await db.commit()

            # 8. Clean up temp file after successful commit
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info("[Worker] Cleaned up temporary file: {}", filepath)

            # 9. Send success notification (decoupled from DB transaction)
            if org_email:
                await send_ingestion_alert(doc_id, doc.filename, "completed", to_email=org_email)

            logger.info("[Worker] Ingestion job COMPLETED successfully for {}", doc_id)

        except Exception:
            # Roll back this session's transaction
            await db.rollback()
            # Propagate to the outer handler which uses a fresh session
            raise


async def ingest_document_job(ctx, doc_id: str, filepath: str):
    """
    arq job entry point for document ingestion.

    Wraps _run_ingestion in asynciso.wait_for() so that a timeout explicitly
    raises asyncio.TimeoutError, which is caught below and triggers cleanup.
    Without this, arq can silently kill the job (SIGKILL on worker restart)
    and the document gets permanently stuck at "processing".
    """
    logger.info("[Worker] Starting ingestion job for Document UUID: {}", doc_id)
    try:
        await asyncio.wait_for(_run_ingestion(ctx, doc_id, filepath), timeout=JOB_TIMEOUT_SECONDS)
    except TimeoutError:
        error_msg = (
            f"Job exceeded maximum allowed time of {JOB_TIMEOUT_SECONDS} seconds. "
            f"The file may be too large or the embedding service is slow."
        )
        logger.error("[Worker] TIMEOUT for document {}. {}", doc_id, error_msg)
        await _mark_document_failed(doc_id, filepath, error_msg)
        # Do not re-raise — let arq consider the job complete (it already failed in DB)
    except Exception as e:
        error_msg = str(e)
        logger.error("[Worker] FAILED for document {}: {}", doc_id, error_msg)
        await _mark_document_failed(doc_id, filepath, error_msg)
        raise  # Re-raise so arq records this as a job failure in Redis


class WorkerSettings:
    functions = [ingest_document_job]  # noqa: RUF012
    redis_settings = redis_settings

    # Maximum concurrent jobs running at the same time in this worker process
    max_jobs = 5

    # Prevent arq from auto-retrying failed jobs.
    # Re-tries must be triggered explicitly by re-uploading the file.
    # This prevents a cascading failure loop on large file processing.
    max_tries = 1

    # Hard ceiling: arq will cancel the task coroutine if it exceeds this.
    # Our asyncio.wait_for() should trigger first at JOB_TIMEOUT_SECONDS,
    # but this is the last-resort safety net.
    job_timeout = JOB_TIMEOUT_SECONDS + 30  # Slightly above our internal timeout
