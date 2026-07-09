import hashlib
import uuid

from fastapi import UploadFile, status
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
    async def ingest_document(
        cls,
        db: AsyncSession,
        file: UploadFile,
        organization_id: str | None = None,
        source_type: SourceType | None = None,
        module: str | None = None,
    ):
        logger.info(f"Starting ingestion process for file: {file.filename}")

        #  STEP 1-2: Validate source_type and file type
        file_config, file_extension = cls._validate_file(file, source_type)

        try:
            #  STEP 3: Read the file into memory
            file_bytes = await file.read()

            #  STEP 4: Enforce maximum file size
            if len(file_bytes) == 0:
                raise AppError("Uploaded file is empty.", status.HTTP_400_BAD_REQUEST)
            if len(file_bytes) > MAX_FILE_SIZE:
                raise AppError(
                    "File size exceeds the 10MB limit.",
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
            logger.info(f"File read successfully. Size: {len(file_bytes)} bytes.")

            #  STEP 5: Hash the file content for deduplication
            # If the same file is uploaded twice (even with a different name),
            # the hash will be identical, and we can reject it in the next step.
            file_hash = hashlib.sha256(file_bytes).hexdigest()
            logger.info(f"File hashed successfully. Hash: {file_hash[:16]}...")

            #  STEP 5-6: Check database for duplicates and existing documents to overwrite
            existing_doc = await cls._check_database_for_duplicates(
                db, organization_id, module, file_hash
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

            #  STEP 8: Chunk the text
            logger.info("Chunking text for AI embedding...")
            chunks = TextChunker.chunk_text(parsed_text)
            logger.info(f"Generated {len(chunks)} chunks.")

            #  STEP 9: Embed the chunks via OpenAI (RISKIEST STEP — must happen before ANY deletion)
            # If this fails, we have not touched Postgres or Qdrant yet, so no data is lost.
            vectors = []
            if chunks:
                logger.info(
                    f"Generating embeddings for {len(chunks)} chunks via OpenAI..."
                )
                vectors = await Embedder.embed_documents(chunks)

            # Embeddings confirmed. Now mutate the databases. ---

            if existing_doc:
                # OVERWRITE PATH: Update in-place to preserve the original UUID
                logger.info(
                    f"Overwriting document {existing_doc.id}. Deleting old Qdrant vectors..."
                )
                await VectorStore.delete_by_document_id(str(existing_doc.id))

                # Update Postgres row in-place (keeps same UUID and created_at!)
                existing_doc.file_hash = file_hash
                existing_doc.filename = file.filename
                existing_doc.file_type = file_config["label"]
                existing_doc.status = "completed"
                document_id_str = str(existing_doc.id)
                logger.info(
                    "Old Qdrant vectors deleted. Proceeding with fresh ingestion."
                )
            else:
                # NEW UPLOAD PATH: Create a fresh Postgres record
                logger.info("No existing document found. Creating new document record.")
                new_document = Document(
                    organization_id=organization_id,
                    filename=file.filename,
                    file_hash=file_hash,
                    file_type=file_config["label"],
                    source_type=source_type,
                    module=module,
                    status="completed",
                )
                db.add(new_document)
                await db.flush()
                document_id_str = str(new_document.id)

            if chunks and vectors:
                #  STEP 10: Store vectors in Qdrant
                await cls._upsert_to_qdrant(
                    chunks,
                    vectors,
                    document_id_str,
                    organization_id,
                    source_type,
                    module,
                )

            await db.commit()
            doc_to_refresh = existing_doc if existing_doc else new_document
            await db.refresh(doc_to_refresh)
            logger.info(
                f"Ingestion completed successfully for document ID: {doc_to_refresh.id}"
            )

            return {
                "document_id": document_id_str,
                "filename": file.filename,
                "file_type": file_config["label"],
                "source_type": source_type.value if source_type else None,
                "module": module,
                "chunks_created": len(chunks),
                "parsed_text_preview": parsed_text[:200]
                + ("..." if len(parsed_text) > 200 else ""),
            }

        except AppError:
            # Re-raise our clean AppError — the global handler will send the right HTTP response.
            await db.rollback()
            raise
        except ValueError as e:
            # Typically thrown by the parsers (e.g., invalid JSON syntax).
            await db.rollback()
            raise AppError(str(e), status.HTTP_400_BAD_REQUEST) from e
        except Exception as e:
            # Catch-all for unexpected failures (network errors, DB issues, etc.)
            await db.rollback()
            raise AppError(
                f"An error occurred: {e!s}", status.HTTP_500_INTERNAL_SERVER_ERROR
            ) from e

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
        if organization_id and module:
            exact_duplicate = await db.execute(
                select(Document).where(
                    Document.organization_id == organization_id,
                    Document.module == module,
                    Document.file_hash == file_hash,
                )
            )
            if exact_duplicate.scalar_one_or_none():
                raise AppError(
                    "This exact file is already active in this module.",
                    status.HTTP_409_CONFLICT,
                )

            logger.info(
                f"Checking for existing document in org [{organization_id}] module [{module}]"
            )
            existing_result = await db.execute(
                select(Document).where(
                    Document.organization_id == organization_id,
                    Document.module == module,
                )
            )
            existing_doc = existing_result.scalar_one_or_none()
            if existing_doc:
                logger.info(
                    f"Found existing document (ID: {existing_doc.id}). Will overwrite after embedding succeeds."
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
