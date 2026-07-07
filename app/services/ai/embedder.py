from openai import AsyncOpenAI

from app.config.settings import settings


class Embedder:
    _client = None

    @classmethod
    def get_client(cls) -> AsyncOpenAI:
        if cls._client is None:
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is not set in environment.")
            cls._client = AsyncOpenAI(api_key=settings.openai_api_key)
        return cls._client

    @classmethod
    async def embed_documents(cls, texts: list[str]) -> list[list[float]]:
        client = cls.get_client()
        response = await client.embeddings.create(
            input=texts, model=settings.open_model_name
        )

        embeddings = sorted(response.data, key=lambda x: x.index)
        return [emb.embedding for emb in embeddings]
