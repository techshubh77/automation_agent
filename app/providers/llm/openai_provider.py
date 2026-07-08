from langchain_openai import ChatOpenAI

from app.config.settings import settings


class OpenAIProvider:
    """
    Single Responsibility: This class only knows how to build and configure OpenAI models.
    """
    _client: ChatOpenAI | None = None

    @classmethod
    def get_client(cls) -> ChatOpenAI:
        if cls._client is None:
            cls._client = ChatOpenAI(
                model=settings.openai_chat_model,
                api_key=settings.openai_api_key,
                temperature=0.7,
                timeout=15.0,
                max_retries=2,
            )
        return cls._client
