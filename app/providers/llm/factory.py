from langchain_core.language_models.chat_models import BaseChatModel

from app.config.settings import settings
from app.providers.llm.groq_provider import GroqProvider
from app.providers.llm.openai_provider import OpenAIProvider


class LLMFactory:
    """
    The Orchestrator Factory.
    The rest of the application will call this class to get a list of LLMs,
    """

    @staticmethod
    def get_robust_llm() -> BaseChatModel:
        """
        Returns a primary LLM configured with an automatic fallback list.
        If the primary fails (e.g. Groq is down), LangChain seamlessly routes to the backup.
        """
        primary_llm = OpenAIProvider.get_client()
        backup_llm = GroqProvider.get_client()

        # Build native LangChain fallback chain
        return primary_llm.with_fallbacks([backup_llm])

    @staticmethod
    def get_primary_model_info() -> dict:
        """
        Returns information about the primary LLM used by this factory.
        Used by the Pricing Engine to calculate costs.
        In a more advanced setup, LangChain's callbacks could be used to detect
        if a fallback was actually triggered, but for now we assume the primary.
        """
        return {
            "provider": "openai",
            "model": settings.openai_chat_model
        }
