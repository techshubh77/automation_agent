import hashlib
import os
import uuid

import aiofiles
from sqlalchemy import select

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


async def ingest_document_job(ctx, doc_id: str, filepath: str):
    logger.info(f"[Worker] Starting ingestion job for Document UUID: {doc_id}")

    async with AsyncSessionLocal() as db:
        try:
            # 1. Fetch document and related organization
            doc = await db.get(Document, uuid.UUID(doc_id))
            if not doc:
                logger.error(f"[Worker] Document {doc_id} not found in database.")
                return

            doc.status = "processing"
            await db.commit()

            # Fetch organization to get the email address
            org_email = None
            if doc.organization_id:
                org_query = select(Organization).where(
                    Organization.org_id == doc.organization_id
                )
                org_result = await db.execute(org_query)
                org = org_result.scalars().first()
                if org and org.email:
                    org_email = org.email

            # 2. Read file from shared storage asynchronously
            if not os.path.exists(filepath):
                raise FileNotFoundError(
                    f"[Worker] File not found on shared storage path: {filepath}"
                )

            async with aiofiles.open(filepath, "rb") as f:
                file_bytes = await f.read()

            file_hash = hashlib.sha256(file_bytes).hexdigest()

            # 3. Select parser using centralized config
            file_extension = None
            for ext, config in SUPPORTED_FILE_TYPES.items():
                if config["label"] == doc.file_type:
                    file_extension = ext
                    parser = config["parser"]
                    break

            if not file_extension:
                raise ValueError(
                    f"[Worker] Unsupported document file type label: {doc.file_type}"
                )

            parsed_text = parser.parse_file_content(file_bytes)
            logger.info(
                f"[Worker] File parsed successfully. Character length: {len(parsed_text)}"
            )

            # 4. Chunk & Embed
            chunks = TextChunker.chunk_text(parsed_text)
            logger.info(f"[Worker] Generated {len(chunks)} text chunks.")

            vectors = []
            if chunks:
                logger.info(
                    f"[Worker] Requesting embeddings from OpenAI for {len(chunks)} chunks..."
                )
                vectors = await Embedder.embed_documents(chunks)

            # 5. Prevent Orphaned Vectors (CRITICAL FIX)
            logger.info(
                f"[Worker] Deleting old vectors for document {doc_id} to prevent orphans..."
            )
            await VectorStore.delete_by_document_id(doc_id)

            # 6. Upsert to Qdrant Vector Store
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
                await VectorStore.upsert_chunks(
                    ids=point_ids, vectors=vectors, payloads=payloads
                )

            # 7. Complete Postgres transaction
            doc.file_hash = file_hash
            doc.status = "completed"
            doc.error_message = None
            await db.commit()

            # Clean up shared file after successful ingestion
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"[Worker] Cleaned up temporary file: {filepath}")

            # Decouple email notification from DB transaction
            if org_email:
                await send_ingestion_alert(
                    doc_id, doc.filename, "completed", to_email=org_email
                )
            logger.info(f"[Worker] Ingestion job completed successfully for {doc_id}")

        except Exception as e:
            logger.error(f"[Worker] Job execution failed for {doc_id}: {e!s}")
            await db.rollback()

            # Fetch again in a new transaction context to mark as failed
            failed_doc = await db.get(Document, uuid.UUID(doc_id))
            if failed_doc:
                failed_doc.status = "failed"
                failed_doc.error_message = str(e)
                await db.commit()

                if failed_doc.organization_id:
                    org_query = select(Organization).where(
                        Organization.org_id == failed_doc.organization_id
                    )
                    org_result = await db.execute(org_query)
                    org = org_result.scalars().first()
                    if org and org.email:
                        await send_ingestion_alert(
                            doc_id,
                            failed_doc.filename,
                            "failed",
                            to_email=org.email,
                            error_message=str(e),
                        )

            if os.path.exists(filepath):
                os.remove(filepath)

            raise e


class WorkerSettings:
    functions = [ingest_document_job]  # noqa: RUF012
    redis_settings = redis_settings
