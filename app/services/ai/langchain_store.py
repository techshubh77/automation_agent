from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore

from app.config.settings import settings
from app.services.ai.vector_store import VectorStore


class LangchainStore:
    _vector_store = None

    @classmethod
    def get_vector_store(cls) -> QdrantVectorStore:
        if cls._vector_store is None:
            client = VectorStore.get_client()
            embeddings = OpenAIEmbeddings(
                api_key=settings.openai_api_key, model=settings.openai_embedding_model
            )
            cls._vector_store = QdrantVectorStore(
                client=client,
                collection_name=VectorStore.COLLECTION_NAME,
                embedding=embeddings,
            )
        return cls._vector_store
