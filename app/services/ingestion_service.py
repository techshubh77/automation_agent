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

# The maximum size we allow for an uploaded file.
# 10 MB is a generous but safe limit for text-based documents (JSON or Markdown).
# This stops someone from uploading a 500MB file and crashing the server.
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

# A lookup table that maps an accepted file extension to:
#   - its expected MIME type (the Content-Type the browser/Postman sends)
#   - the parser class that knows how to convert its bytes into plain text
#   - a short label we store in the database so we know what kind of file it was
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
        project_id: str | None = None,
        source_type: SourceType | None = None,
    ):
        logger.info(f"Starting ingestion process for file: {file.filename}")

        # ── STEP 1: Validate source_type ──────────────────────────────────────
        # source_type tells us the business purpose of the document:
        # Is it an 'api_doc' (developer documentation) or a 'knowledge_base' (company info)?
        # We must reject any value that's not in our SourceType enum.
        # This prevents garbage data like source_type="haha" from polluting Qdrant.
        if source_type is None:
            raise AppError(
                f"source_type is required. Allowed values: {[e.value for e in SourceType]}", 400
            )

        # ── STEP 2: Detect and validate the file type ─────────────────────────
        # We support .json and .md files. We figure out which one it is by
        # looking at the file extension (what's at the end of the filename).
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
        # For example, someone could rename a .exe file to .json to try to sneak it in.
        # The browser/client always sends the real Content-Type header, so we check that too.
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
            # ── STEP 3: Read the file into memory ─────────────────────────────
            # We read all the raw bytes at once. This is safe because we check
            # the size immediately after (Step 4).
            file_bytes = await file.read()

            # ── STEP 4: Enforce maximum file size ─────────────────────────────
            # We check size AFTER reading (not before) because UploadFile doesn't
            # give us the size until we've read the content.
            if len(file_bytes) > MAX_FILE_SIZE:
                raise AppError("File size exceeds the 10MB limit.", 413)
            logger.info(f"File read successfully. Size: {len(file_bytes)} bytes.")

            # ── STEP 5: Hash the file content for deduplication ───────────────
            # SHA-256 generates a unique "fingerprint" of the file's content.
            # If the same file is uploaded twice (even with a different name),
            # the hash will be identical, and we can reject it in the next step.
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            logger.info(f"File hashed successfully. Hash: {file_hash[:16]}...")

            # ── STEP 6: Check for duplicate uploads ───────────────────────────
            # Query the database to see if we already have a document with this
            # exact same content hash. If yes, reject with 409 Conflict.
            # This prevents the same knowledge from being stored twice in Qdrant,
            # which would cause duplicate answers in the chat API.
            existing = await db.execute(
                select(Document).where(Document.file_hash == file_hash)
            )
            if existing.scalar_one_or_none():
                raise AppError(
                    "This file has already been ingested. Duplicate uploads are not allowed.", 409
                )

            # ── STEP 7: Parse the file into plain text ────────────────────────
            # This is the polymorphic part of the pipeline.
            # We look up the correct parser from our SUPPORTED_FILE_TYPES table.
            #
            # For .json: JsonParser.parse_file_content() flattens nested JSON
            #            into readable "key -> subkey: value" text lines.
            # For .md:   MarkdownParser.parse_file_content() simply decodes
            #            the bytes to a UTF-8 string (Markdown is already text).
            #
            # The beautiful thing here is that regardless of input format,
            # we always get back a single plain text string to pass to the AI.
            parser = file_config["parser"]
            parsed_text = parser.parse_file_content(file_bytes)
            logger.info(f"Parsed {file_extension} file into text. Length: {len(parsed_text)} characters.")

            # ── STEP 8: Save a record to PostgreSQL ───────────────────────────
            # We save to the database BEFORE upserting to Qdrant so that:
            # a) We get a unique document UUID (new_document.id)
            # b) If Qdrant fails, we can roll back the DB record too (atomicity)
            new_document = Document(
                organization_id=organization_id,
                project_id=project_id,
                filename=file.filename,
                file_hash=file_hash,
                file_type=file_config["label"],  # "json" or "markdown"
                source_type=source_type,
                status="completed",
            )

            db.add(new_document)
            # flush() sends the INSERT to the DB session so we get the new UUID
            # back, but does NOT commit yet — it's still inside our transaction.
            await db.flush()

            document_id_str = str(new_document.id)

            # ── STEP 9: Chunk the text ────────────────────────────────────────
            # Large documents need to be split into smaller pieces ("chunks") before
            # embedding. This is because:
            # a) AI models can only process a limited amount of text at once
            # b) Smaller, focused chunks produce more precise similarity search results
            #
            # LangChain's RecursiveCharacterTextSplitter (inside TextChunker) works
            # great for both JSON text and Markdown — it tries to split on paragraph
            # breaks first (double newlines), then single newlines, then spaces.
            # This keeps logical paragraphs and headings together whenever possible.
            logger.info("Chunking text for AI embedding...")
            chunks = TextChunker.chunk_text(parsed_text)
            logger.info(f"Generated {len(chunks)} chunks.")

            if chunks:
                # ── STEP 10: Embed the chunks via OpenAI ──────────────────────
                # We send all chunk texts to OpenAI's text-embedding-3-small model.
                # It converts each chunk into a list of 1536 numbers (a "vector")
                # that mathematically represents the meaning of that chunk.
                logger.info(
                    f"Generating embeddings for {len(chunks)} chunks via OpenAI..."
                )
                vectors = await Embedder.embed_documents(chunks)

                # ── STEP 11: Store vectors in Qdrant ──────────────────────────
                # We upsert all the chunk vectors into our Qdrant collection.
                # Each point (vector) also carries a "payload" — metadata we can
                # filter by later, like which organization or project owns this chunk.
                logger.info("Upserting embedded vectors to Qdrant Vector Store...")
                point_ids = [str(uuid.uuid4()) for _ in chunks]
                payloads = [
                    {
                        "document_id": document_id_str,
                        "organization_id": organization_id,
                        "project_id": project_id,
                        "source_type": source_type,
                        "chunk_index": i,
                        "text": chunk,
                    }
                    for i, chunk in enumerate(chunks)
                ]

                # This runs in a thread pool so the async event loop is never blocked
                # while Qdrant is doing its work (see vector_store.py for details).
                await VectorStore.upsert_chunks(
                    ids=point_ids, vectors=vectors, payloads=payloads
                )
                logger.info("Successfully upserted chunks to Qdrant.")

            # ── STEP 12: Commit the transaction ───────────────────────────────
            # Only now, after everything has succeeded (parsing, embedding, Qdrant),
            # do we commit the PostgreSQL transaction.
            # If anything above failed, we'd have hit the except block and rolled back.
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
