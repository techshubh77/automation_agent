from pathlib import Path

from fastapi import status
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from qdrant_client.http import models as rest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.settings import settings
from app.exceptions.custom_exceptions import AppError
from app.models.conversation import Conversation
from app.models.message import Message
from app.providers.llm.factory import LLMFactory
from app.schemas.chat_schema import ChatRequestSchema
from app.services.ai.langchain_store import LangchainStore
from app.utils.logger import logger

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
with open(PROMPTS_DIR / "system_prompt.txt", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()

class ChatService:
    @classmethod
    async def chat(cls, data: ChatRequestSchema, db: AsyncSession) -> tuple[str, str]:
        logger.info(f"Received chat request: {data.message}")

        try:
            # 1. Manage Conversation Session
            if not data.conversation_id:
                logger.info("No conversation_id provided. Starting a new chat session.")
                # Generate a short title from the first prompt (max 50 chars)
                generated_title = data.message[:50] + (
                    "..." if len(data.message) > 50 else ""
                )

                new_conv = Conversation(
                    organization_id=data.organization_id,
                    user_id=data.user_id,
                    title=generated_title,
                )
                db.add(new_conv)
                await db.flush()
                conv_uuid = new_conv.id
            else:
                logger.info(f"Resuming conversation {data.conversation_id}")
                conv_uuid = (
                    data.conversation_id
                )  # Already a UUID, validated by Pydantic schema
                # Verify conversation exists
                existing = await db.execute(
                    select(Conversation).where(Conversation.id == conv_uuid)
                )
                if not existing.scalar_one_or_none():
                    raise AppError(
                        f"Conversation {data.conversation_id} not found",
                        status.HTTP_404_NOT_FOUND,
                    )

            # 2. Save the Human Message
            db.add(
                Message(
                    conversation_id=conv_uuid,
                    role="human",
                    content=data.message,
                )
            )
            await db.flush()

            # 3. Retrieve Memory (Sliding Window: Last 10 messages / 5 turns)
            langchain_messages = await cls._get_conversation_history(db, conv_uuid)

            # 4. Execute Vector Search (RAG)
            formatted_context = await cls._retrieve_context(
                data.message, data.organization_id, data.module
            )

            # 6. Build the Chat Prompt with Memory
            qa_prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", SYSTEM_PROMPT + "\n\nContext Documents:\n{context}"),
                    MessagesPlaceholder(variable_name="chat_history"),
                ]
            )

            # 7. Execute Native LangChain Fallback
            logger.info("Retrieving robust LLM from Factory...")
            robust_llm = LLMFactory.get_robust_llm()

            chain = qa_prompt | robust_llm | StrOutputParser()

            logger.info(
                "Executing RAG chain with conversational memory and native fallback logic..."
            )
            try:
                reply = await chain.ainvoke(
                    {"context": formatted_context, "chat_history": langchain_messages}
                )
            except Exception as e:
                logger.critical(f"ALL LLM PROVIDERS FAILED: {e!s}")
                raise AppError(
                    "I am temporarily unavailable due to high server load. Please try again in a few minutes.",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                ) from e

            # 8. Save the AI Message
            db.add(
                Message(
                    conversation_id=conv_uuid,
                    role="ai",
                    content=reply,
                )
            )
            await db.commit()

            return reply, str(conv_uuid)

        except AppError:
            await db.rollback()
            raise
        except ValueError as e:
            await db.rollback()
            raise AppError(f"Invalid input: {e!s}", status.HTTP_400_BAD_REQUEST) from e
        except Exception as e:
            await db.rollback()
            logger.error(f"Unexpected Chat Error: {e!s}")
            raise AppError(
                "An unexpected error occurred during chat processing.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    @staticmethod
    async def index(org_id: str, db: AsyncSession):
        """Retrieve chat history (conversations and their messages) for an organization."""
        stmt = (
            select(Conversation)
            .where(Conversation.organization_id == org_id)
            .options(selectinload(Conversation.messages))
            .order_by(Conversation.created_at.desc())
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def _get_conversation_history(db: AsyncSession, conv_uuid) -> list:
        logger.info("Fetching last 10 messages for context window...")
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_uuid)
            .order_by(Message.created_at.desc())
            .limit(10)
        )
        db_messages = list(result.scalars().all())
        db_messages.reverse()

        langchain_messages = []
        for msg in db_messages:
            if msg.role == "human":
                langchain_messages.append(HumanMessage(content=msg.content))
            elif msg.role == "ai":
                langchain_messages.append(AIMessage(content=msg.content))
        return langchain_messages

    @staticmethod
    async def _retrieve_context(
        message: str, organization_id: str | None, module: str | None
    ) -> str:
        filter_conditions = []
        if organization_id:
            filter_conditions.append(
                rest.FieldCondition(
                    key="metadata.organization_id",
                    match=rest.MatchValue(value=organization_id),
                )
            )
        if module:
            filter_conditions.append(
                rest.FieldCondition(
                    key="metadata.module", match=rest.MatchValue(value=module)
                )
            )

        search_kwargs = {
            "k": settings.top_k_chunks,
            "score_threshold": settings.similarity_threshold,
        }
        if filter_conditions:
            search_kwargs["filter"] = rest.Filter(must=filter_conditions)

        vector_store = LangchainStore.get_vector_store()
        retriever = vector_store.as_retriever(
            search_type="similarity_score_threshold", search_kwargs=search_kwargs
        )

        logger.info("Retrieving documents from Qdrant with metadata filters...")
        docs = await retriever.ainvoke(message)
        return "\n\n---\n\n".join(doc.page_content for doc in docs)
