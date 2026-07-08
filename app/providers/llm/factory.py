from langchain_core.language_models.chat_models import BaseChatModel

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
        primary_llm = GroqProvider.get_client()
        backup_llm = OpenAIProvider.get_client()

        # Build native LangChain fallback chain
        return primary_llm.with_fallbacks([backup_llm])
