from pathlib import Path

from langchain_community.callbacks.manager import get_openai_callback
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from qdrant_client.http import models as rest

from app.config.settings import settings
from app.exceptions.custom_exceptions import AppError
from app.schemas.chat_schema import ChatRequestSchema
from app.services.ai.langchain_store import LangchainStore
from app.utils.logger import logger

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
with open(PROMPTS_DIR / "system_prompt.txt", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


class ChatService:
    _llm: ChatOpenAI | None = None

    @classmethod
    def get_llm(cls) -> ChatOpenAI:
        if cls._llm is None:
            cls._llm = ChatOpenAI(
                model=settings.openai_chat_model,
                api_key=settings.openai_api_key,
                temperature=0.7,
            )
        return cls._llm

    @staticmethod
    async def chat(data: ChatRequestSchema) -> str:
        logger.info(f"Received chat request: {data.message}")

        # Build filter from metadata if provided
        filter_conditions = []
        if data.organization_id:
            filter_conditions.append(
                rest.FieldCondition(
                    key="organization_id",
                    match=rest.MatchValue(value=data.organization_id),
                )
            )
        if data.project_id:
            filter_conditions.append(
                rest.FieldCondition(
                    key="project_id", match=rest.MatchValue(value=data.project_id)
                )
            )

        search_kwargs = {
            "k": settings.top_k_chunks,
            "score_threshold": settings.similarity_threshold,
        }
        if filter_conditions:
            search_kwargs["filter"] = rest.Filter(must=filter_conditions)

        try:
            logger.debug(
                f"Calling OpenAI API using model: {settings.openai_chat_model}"
            )
            llm = ChatService.get_llm()

            vector_store = LangchainStore.get_vector_store()
            retriever = vector_store.as_retriever(
                search_type="similarity_score_threshold", search_kwargs=search_kwargs
            )

            logger.info("Retrieving documents from Qdrant with metadata filters...")
            docs = await retriever.ainvoke(data.message)
            logger.info(
                f"Retrieved {len(docs)} documents above the {settings.similarity_threshold} threshold."
            )

            formatted_context = "\n\n---\n\n".join(doc.page_content for doc in docs)

            qa_prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", SYSTEM_PROMPT + "\n\nContext Documents:\n{context}"),
                    ("human", "{input}"),
                ]
            )

            rag_chain = qa_prompt | llm | StrOutputParser()

            logger.info("Executing RAG chain...")
            with get_openai_callback() as cb:
                reply = await rag_chain.ainvoke(
                    {"context": formatted_context, "input": data.message}
                )

                logger.info("OpenAI API call successful. Returning response to user.")
                logger.info(
                    f"Token Usage - Prompt: {cb.prompt_tokens} | Completion: {cb.completion_tokens} | Total: {cb.total_tokens} | Est. Cost: ${cb.total_cost:.5f}"
                )
                logger.debug(f"Response: {reply}")

            return reply
        except Exception as e:
            logger.error(f"Unexpected Chat Error: {e!s}")
            raise AppError(
                "An unexpected error occurred during chat processing.", 500
            ) from e
