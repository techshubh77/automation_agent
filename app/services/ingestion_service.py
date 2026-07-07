import hashlib
import uuid

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.custom_exceptions import AppError
from app.models.document import Document
from app.schemas.source_type_schema import SourceType
from app.services.ai.embedder import Embedder
from app.services.ai.vector_store import VectorStore
from app.services.ingestion.chunker import TextChunker
from app.services.ingestion.json_parser import JsonParser
from app.services.ingestion.markdown_parser import MarkdownParser
from app.utils.logger import logger

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

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
    @staticmethod
    async def ingest_document(
        db: AsyncSession,
        file: UploadFile,
        organization_id: str | None = None,
        source_type: SourceType | None = None,
        module: str | None = None,
    ):
        logger.info(f"Starting ingestion process for file: {file.filename}")

        #  STEP 1: Validate source_type
        if source_type is None:
            raise AppError(
                f"source_type is required. Allowed values: {[e.value for e in SourceType]}",
                400,
            )

        #  STEP 2: Detect and validate the file type
        file_extension = None
        for ext in SUPPORTED_FILE_TYPES:
            if file.filename.endswith(ext):
                file_extension = ext
                break

        # If the extension is not in our supported list, reject immediately.
        if file_extension is None:
            logger.warning(f"Unsupported file type uploaded: {file.filename}")
            raise AppError(
                f"Unsupported file type. Accepted formats: {list(SUPPORTED_FILE_TYPES.keys())}",
                400,
            )

        # Look up the configuration for this file type from our lookup table above.
        file_config = SUPPORTED_FILE_TYPES[file_extension]

        # Double-check the MIME type to prevent spoofing.
        if file.content_type != file_config["mime"]:
            logger.warning(
                f"MIME type mismatch for {file.filename}: "
                f"expected {file_config['mime']}, got {file.content_type}"
            )
            raise AppError(
                f"Invalid Content-Type for a {file_extension} file. "
                f"Expected: {file_config['mime']}",
                400,
            )

        try:
            #  STEP 3: Read the file into memory
            file_bytes = await file.read()

            #  STEP 4: Enforce maximum file size
            if len(file_bytes) > MAX_FILE_SIZE:
                raise AppError("File size exceeds the 10MB limit.", 413)
            logger.info(f"File read successfully. Size: {len(file_bytes)} bytes.")

            #  STEP 5: Hash the file content for deduplication
            # If the same file is uploaded twice (even with a different name),
            # the hash will be identical, and we can reject it in the next step.
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            logger.info(f"File hashed successfully. Hash: {file_hash[:16]}...")

            #  STEP 6: Check for duplicate uploads
            existing = await db.execute(
                select(Document).where(Document.file_hash == file_hash)
            )
            if existing.scalar_one_or_none():
                raise AppError(
                    "This file has already been ingested. Duplicate uploads are not allowed.",
                    409,
                )

            #  STEP 7: Parse the file into plain text
            # For .json: JsonParser.parse_file_content() flattens nested JSON
            #            into readable "key -> subkey: value" text lines.
            # For .md:   MarkdownParser.parse_file_content() simply decodes
            #            the bytes to a UTF-8 string (Markdown is already text).
            parser = file_config["parser"]
            parsed_text = parser.parse_file_content(file_bytes)
            logger.info(
                f"Parsed {file_extension} file into text. Length: {len(parsed_text)} characters."
            )

            #  STEP 8: Save a record to PostgreSQL
            new_document = Document(
                organization_id=organization_id,
                filename=file.filename,
                file_hash=file_hash,
                file_type=file_config["label"],  # "json" or "markdown"
                source_type=source_type,
                module=module,
                status="completed",
            )

            db.add(new_document)
            await db.flush()

            document_id_str = str(new_document.id)

            #  STEP 9: Chunk the text
            logger.info("Chunking text for AI embedding...")
            chunks = TextChunker.chunk_text(parsed_text)
            logger.info(f"Generated {len(chunks)} chunks.")

            if chunks:
                #  STEP 10: Embed the chunks via OpenAI
                logger.info(
                    f"Generating embeddings for {len(chunks)} chunks via OpenAI..."
                )
                vectors = await Embedder.embed_documents(chunks)

                #  STEP 11: Store vectors in Qdrant
                logger.info("Upserting embedded vectors to Qdrant Vector Store...")
                point_ids = [str(uuid.uuid4()) for _ in chunks]
                payloads = [
                    {
                        "metadata": {
                            "document_id": document_id_str,
                            "organization_id": organization_id,
                            "source_type": source_type,
                            "module": module,
                            "chunk_index": i,
                        },
                        "page_content": chunk,
                    }
                    for i, chunk in enumerate(chunks)
                ]

                # This runs in a thread pool so the async event loop is never blocked
                # while Qdrant is doing its work
                await VectorStore.upsert_chunks(
                    ids=point_ids, vectors=vectors, payloads=payloads
                )
                logger.info("Successfully upserted chunks to Qdrant.")

            #  STEP 12: Commit the transaction
            await db.commit()
            await db.refresh(new_document)
            logger.info(
                f"Ingestion completed successfully for document ID: {new_document.id}"
            )

            return {
                "document_id": document_id_str,
                "filename": file.filename,
                "file_type": file_config["label"],
                "source_type": source_type,
                "module": module,
                "chunks_created": len(chunks),
                "parsed_text_preview": parsed_text[:200] + "...",
            }

        except AppError:
            # Re-raise our clean AppError — the global handler will send the right HTTP response.
            await db.rollback()
            raise
        except ValueError as e:
            # Typically thrown by the parsers (e.g., invalid JSON syntax).
            await db.rollback()
            raise AppError(str(e), 400) from e
        except Exception as e:
            # Catch-all for unexpected failures (network errors, DB issues, etc.)
            await db.rollback()
            raise AppError(f"An error occurred: {e!s}", 500) from e
