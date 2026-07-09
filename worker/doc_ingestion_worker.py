import os
import hashlib
import uuid
from arq.connections import RedisSettings
from app.config.redis import redis_settings
from app.config.database import AsyncSessionLocal
from app.models.document import Document
from app.utils.logger import logger

# Independent client instances / utilities
from app.services.ai.embedder import Embedder
from app.services.ai.vector_store import VectorStore
from app.services.ingestion.chunker import TextChunker
from app.services.ingestion.json_parser import JsonParser
from app.services.ingestion.markdown_parser import MarkdownParser

from app.utils.email_helper import send_ingestion_alert

# Mapping accepted extensions inside worker locally
PARSERS = {
    "json": JsonParser,
    "markdown": MarkdownParser,
}

async def ingest_document_job(ctx, doc_id: str, filepath: str):
    logger.info(f"[Worker] Starting ingestion job for Document UUID: {doc_id}")
    
    async with AsyncSessionLocal() as db:
        try:
            # 1. Update status to processing
            doc = await db.get(Document, doc_id)
            if not doc:
                logger.error(f"[Worker] Document {doc_id} not found in PostgreSQL database.")
                return
            
            doc.status = "processing"
            await db.commit()

            # 2. Read file from shared storage
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"[Worker] File not found on shared storage path: {filepath}")
                
            with open(filepath, "rb") as f:
                file_bytes = f.read()

            file_hash = hashlib.sha256(file_bytes).hexdigest()

            # 3. Select parser locally
            file_type = doc.file_type.lower()
            if file_type not in PARSERS:
                raise ValueError(f"[Worker] Unsupported document file type: {file_type}")
            
            parser = PARSERS[file_type]
            parsed_text = parser.parse_file_content(file_bytes)
            logger.info(f"[Worker] File parsed successfully. Character length: {len(parsed_text)}")

            # 4. Chunk & Embed
            chunks = TextChunker.chunk_text(parsed_text)
            logger.info(f"[Worker] Generated {len(chunks)} text chunks.")
            
            logger.info(f"[Worker] Requesting embeddings from OpenAI for {len(chunks)} chunks...")
            vectors = await Embedder.embed_documents(chunks)

            # 5. Upsert to Qdrant Vector Store
            point_ids = []
            payloads = []
            chunk_namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
            
            for i, chunk in enumerate(chunks):
                chunk_unique_name = f"{doc_id}_chunk_{i}"
                deterministic_uuid = uuid.uuid5(chunk_namespace, chunk_unique_name)
                point_ids.append(str(deterministic_uuid))
                payloads.append({
                    "metadata": {
                        "document_id": doc_id,
                        "organization_id": doc.organization_id,
                        "source_type": doc.source_type,
                        "module": doc.module,
                        "chunk_index": i,
                    },
                    "page_content": chunk,
                })

            logger.info("[Worker] Upserting vectors to Qdrant...")
            await VectorStore.upsert_chunks(
                ids=point_ids, vectors=vectors, payloads=payloads
            )

            # 6. Complete Postgres transaction
            doc.file_hash = file_hash
            doc.status = "completed"
            doc.error_message = None
            await db.commit()

            # Clean up shared file after successful ingestion
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"[Worker] Cleaned up temporary file: {filepath}")
                
            # Send Success Email Notification
            await send_ingestion_alert(doc_id, doc.filename, "completed")
            logger.info(f"[Worker] Ingestion job completed successfully for {doc_id}")

        except Exception as e:
            logger.error(f"[Worker] Job execution failed for {doc_id}: {e!s}")
            # Ensure DB rollback and write failure logs
            await db.rollback()
            doc = await db.get(Document, doc_id)
            if doc:
                doc.status = "failed"
                doc.error_message = str(e)
                await db.commit()
            if os.path.exists(filepath):
                os.remove(filepath)
            
            # Send Failure Email Notification
            filename = doc.filename if doc else os.path.basename(filepath)
            await send_ingestion_alert(doc_id, filename, "failed", error_message=str(e))
            raise e

class WorkerSettings:
    functions = [ingest_document_job]
    redis_settings = redis_settings
