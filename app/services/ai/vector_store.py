import asyncio

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from app.config.settings import settings


class VectorStore:
    _client = None
    COLLECTION_NAME = "automation_agent"

    @classmethod
    def get_client(cls) -> QdrantClient:
        if cls._client is None:
            cls._client = QdrantClient(url=settings.qdrant_url)
        return cls._client

    @classmethod
    def init_collection(cls):
        """Creates collection if not exists"""
        client = cls.get_client()
        if not client.collection_exists(cls.COLLECTION_NAME):
            client.create_collection(
                collection_name=cls.COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=settings.embedding_dimensions, distance=Distance.COSINE
                ),
            )

    @classmethod
    async def upsert_chunks(
        cls, ids: list[str], vectors: list[list[float]], payloads: list[dict]
    ):
        """Upsert points into collection (non-blocking via thread executor)"""
        cls.init_collection()
        client = cls.get_client()
        points = [
            PointStruct(id=idx, vector=vec, payload=pay)
            for idx, vec, pay in zip(ids, vectors, payloads, strict=True)
        ]
        await asyncio.to_thread(
            client.upsert, collection_name=cls.COLLECTION_NAME, points=points
        )

    @classmethod
    async def delete_by_document_id(cls, document_id: str):
        """Delete old vectors for update/overwrite (non-blocking)"""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        client = cls.get_client()
        points_selector = Filter(
            must=[
                FieldCondition(
                    key="metadata.document_id", match=MatchValue(value=document_id)
                )
            ]
        )
        await asyncio.to_thread(
            client.delete,
            collection_name=cls.COLLECTION_NAME,
            points_selector=points_selector,
        )
        """Delete old vectors for update/overwrite"""
