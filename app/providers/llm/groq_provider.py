from langchain_groq import ChatGroq

from app.config.settings import settings


class GroqProvider:
    """
    Single Responsibility: This class only knows how to build and configure Groq models.
    """

    _client: ChatGroq | None = None

    @classmethod
    def get_client(cls) -> ChatGroq:
        if cls._client is None:
            cls._client = ChatGroq(
                model=settings.groq_chat_model,
                api_key=settings.groq_api_key,
                temperature=0.3,
                timeout=15.0,
                max_retries=2,
            )
        return cls._client
