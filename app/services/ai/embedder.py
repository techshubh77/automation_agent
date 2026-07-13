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
    async def embed_documents(cls, texts: list[str]) -> tuple[list[list[float]], int]:
        client = cls.get_client()
        response = await client.embeddings.create(
            input=texts, model=settings.openai_embedding_model
        )

        embeddings = sorted(response.data, key=lambda x: x.index)
        tokens = response.usage.prompt_tokens if response.usage else 0
        return [emb.embedding for emb in embeddings], tokens
