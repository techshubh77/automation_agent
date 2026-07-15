import asyncio
import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import status
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from qdrant_client.http import models as rest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config.database import AsyncSessionLocal
from app.config.settings import settings
from app.exceptions.custom_exceptions import AppError
from app.models.conversation import Conversation
from app.models.credit_usage import CreditUsage
from app.models.message import Message
from app.models.organization import Organization
from app.providers.llm.factory import LLMFactory
from app.schemas.chat_schema import AgentResponse, ChatRequestSchema
from app.services.ai.langchain_store import LangchainStore
from app.services.pricing_engine import PricingEngine
from app.utils.logger import logger

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
with open(PROMPTS_DIR / "system_prompt.txt", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read()


class ChatService:
    _background_tasks = set()

    @classmethod
    def _create_background_task(cls, coro):
        task = asyncio.create_task(coro)
        cls._background_tasks.add(task)
        task.add_done_callback(cls._background_tasks.discard)

    @classmethod
    async def _get_or_create_conversation(cls, data: ChatRequestSchema, db: AsyncSession) -> uuid.UUID:
        if not data.conversation_id:
            logger.info("No conversation_id provided. Starting a new chat session.")
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
            return new_conv.id

        logger.info("Resuming conversation {}", data.conversation_id)
        conv_uuid = data.conversation_id
        existing = await db.execute(
            select(Conversation).where(Conversation.id == conv_uuid)
        )
        if not existing.scalar_one_or_none():
            raise AppError(
                f"Conversation {data.conversation_id} not found",
                status.HTTP_404_NOT_FOUND,
            )
        return conv_uuid

    @classmethod
    async def chat(
        cls, data: ChatRequestSchema, db: AsyncSession
    ) -> tuple[AgentResponse, str]:
        logger.info("Received chat request: {}", data.message)

        try:
            # PRE-FLIGHT: Credit Balance Check 
            # Block the request immediately if the organization has no credits.
            # Uses a standard select. TOCTOU is prevented by the DB CHECK constraint.
            org_result = await db.execute(
                select(Organization)
                .where(Organization.organization_id == data.organization_id)
            )
            org = org_result.scalar_one_or_none()
            if org is None:
                raise AppError(
                    f"Organization '{data.organization_id}' not found.",
                    status.HTTP_404_NOT_FOUND,
                )
            if org.credit_balance <= Decimal("0"):
                raise AppError(
                    "Your organization has insufficient credits. Please top up your balance.",
                    status.HTTP_402_PAYMENT_REQUIRED,
                )

            # 1. Manage Conversation Session
            conv_uuid = await cls._get_or_create_conversation(data, db)

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
            if not data.conversation_id:
                langchain_messages = [HumanMessage(content=data.message)]
            else:
                langchain_messages = await cls._get_conversation_history(db, conv_uuid)

            # 4. Contextual Query Rewriting
            search_query, rewrite_raw_msg = await cls._rewrite_query(langchain_messages, data.message)
            logger.info("Rewritten search query: {}", search_query)

            # 5. Execute Vector Search (RAG)
            formatted_context = await cls._retrieve_context(
                search_query, data.organization_id, data.module
            )

            # 6. Build the Chat Prompt with Memory
            from datetime import datetime
            current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dynamic_system_prompt = f"The current date and time is: {current_time_str}\n\n{SYSTEM_PROMPT}"

            qa_prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", dynamic_system_prompt + "\n\nContext Documents:\n{context}"),
                    MessagesPlaceholder(variable_name="chat_history"),
                ]
            )
 
            # 6. Execute LLM Call
            logger.info("Retrieving robust LLM from Factory...")
            robust_llm = LLMFactory.get_robust_llm()
            structured_llm = robust_llm.with_structured_output(
                AgentResponse, include_raw=True, method="function_calling"
            )
            chain = qa_prompt | structured_llm

            logger.info(
                "Executing RAG chain with conversational memory and structured output..."
            )
            try:
                response = await chain.ainvoke(
                    {"context": formatted_context, "chat_history": langchain_messages}
                )
            except Exception as e:
                logger.critical("ALL LLM PROVIDERS FAILED: {}", str(e))
                raise AppError(
                    "I am temporarily unavailable due to high server load. Please try again in a few minutes.",
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                ) from e

            # 7. BILLING — committed in its own independent transaction
            cls._create_background_task(
                cls._commit_billing(
                    raw_msg=response["raw"],
                    organization_id=data.organization_id,
                    conv_uuid=conv_uuid,
                    model_info=LLMFactory.get_primary_model_info(),
                    operation_type="chat",
                )
            )

            if rewrite_raw_msg:
                cls._create_background_task(
                    cls._commit_billing(
                        raw_msg=rewrite_raw_msg,
                        organization_id=data.organization_id,
                        conv_uuid=conv_uuid,
                        model_info={"provider": "openai", "model": "gpt-4o-mini"},
                        operation_type="query_rewrite",
                    )
                )

            # Check if LLM refused to return the structured JSON or failed parsing
            agent_response: AgentResponse = response.get("parsed")
            if not agent_response:
                parsing_error = response.get("parsing_error")
                logger.error("LLM failed to return valid structured output. Error: {}", parsing_error)
                raise AppError(
                    "I am having trouble processing that request. Could you please rephrase it?",
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            # 8. Save the AI Message
            meta_data = {
                "flag": agent_response.flag,
                "preview": agent_response.preview,
                "payload": agent_response.payload.model_dump()
                if agent_response.payload
                else None,
                "missing_fields": agent_response.missing_fields,
                "payload_example": agent_response.payload_example,
            }
            db.add(
                Message(
                    conversation_id=conv_uuid,
                    role="ai",
                    content=agent_response.reply,
                    meta_data=meta_data,
                )
            )
            await db.commit()

            return agent_response, str(conv_uuid)

        except AppError:
            await db.rollback()
            raise
        except ValueError as e:
            await db.rollback()
            raise AppError(f"Invalid input: {e!s}", status.HTTP_400_BAD_REQUEST) from e
        except Exception as e:
            await db.rollback()
            logger.error("Unexpected Chat Error: {}", str(e))
            raise AppError(
                "An unexpected error occurred during chat processing.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    @staticmethod
    async def index(organization_id: str, db: AsyncSession, search: str | None = None, limit: int = 10, offset: int = 0):
        """Retrieve chat history (conversations) for an organization."""
        stmt = (
            select(Conversation)
            .where(Conversation.organization_id == organization_id)
        )
        
        if search:
            stmt = stmt.where(Conversation.title.ilike(f"%{search}%"))
            
        stmt = (
            stmt.options(selectinload(Conversation.messages))
            .order_by(Conversation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_conversation(conversation_id: str, db: AsyncSession):
        """Retrieve a specific conversation and all its messages."""
        stmt = (
            select(Conversation)
            .where(Conversation.id == conversation_id)
            .options(selectinload(Conversation.messages))
        )
        result = await db.execute(stmt)
        conversation = result.scalars().first()
        if not conversation:
            raise AppError("Conversation not found", status.HTTP_404_NOT_FOUND)

        conversation.messages.sort(key=lambda x: x.created_at)
        return conversation

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

    @classmethod
    async def _commit_billing(
        cls,
        raw_msg,
        organization_id: str,
        conv_uuid: uuid.UUID,
        model_info: dict,
        operation_type: str = "chat",
    ) -> None:
        """
        Persists the credit usage record and deducts credits from the organization
        in a fully independent database transaction.

        WHY A SEPARATE TRANSACTION:
        The LLM has already been called and the provider has been charged real money.
        Billing must be committed regardless of what happens to the chat message save.
        If the chat transaction rolls back (e.g., DB error saving the AI message), the
        billing must NOT roll back — the usage already happened.

        WHY ATOMIC SQL ARITHMETIC:
        We use `SET credit_balance = credit_balance - X` (not read-then-write) so that
        PostgreSQL evaluates the arithmetic atomically at the DB level, preventing
        lost-update race conditions on concurrent requests from the same organization.
        """
        input_tok, output_tok, total_tok = cls._extract_token_counts(raw_msg)

        if total_tok <= 0:
            logger.warning(
                "Billing skipped: no token usage reported. Org: {} | Ref: {}",
                organization_id,
                str(conv_uuid),
            )
            return

        # Get the provider and model that were actually used
        # Calculate the exact cost using Decimal precision
        breakdown = PricingEngine.calculate(
            provider=model_info["provider"],
            model=model_info["model"],
            input_tokens=input_tok,
            output_tokens=output_tok,
            organization_id=organization_id,
            reference_id=str(conv_uuid),
        )

        logger.info(
            "Billing calculated: {} credits for {} tokens | Org: {}",
            breakdown.credits_used,
            total_tok,
            organization_id,
        )

        # Open an independent session that is not tied to the chat request transaction
        async with AsyncSessionLocal() as billing_db:
            try:
                # Persist the usage audit record
                billing_db.add(
                    CreditUsage(
                        organization_id=organization_id,
                        reference_id=str(conv_uuid),
                        operation_type=operation_type,
                        credits_used=breakdown.credits_used,
                        status="completed",
                        cost_breakdown=breakdown.model_dump(mode="json"),
                    )
                )

                # Atomic SQL arithmetic deduction — PostgreSQL evaluates credit_balance - X
                # at the row level, making this safe under concurrent requests
                await billing_db.execute(
                    update(Organization)
                    .where(Organization.organization_id == organization_id)
                    .values(
                        credit_balance=Organization.credit_balance - breakdown.credits_used
                    )
                )

                await billing_db.commit()
                logger.info(
                    "Billing committed successfully | Org: {} | Credits deducted: {}",
                    organization_id,
                    breakdown.credits_used,
                )
            except Exception as e:
                await billing_db.rollback()
                # Log and alert — do NOT propagate. The user already received their response.
                logger.error(
                    "BILLING FAILURE (non-fatal) | Org: {} | Ref: {} | Error: {}",
                    organization_id,
                    str(conv_uuid),
                    str(e),
                )

    @staticmethod
    def _extract_token_counts(raw_msg) -> tuple[int, int, int]:
        """
        Extracts input, output, and total token counts from the LangChain raw response.
        Handles both OpenAI-style (usage_metadata) and Groq-style (response_metadata) formats.
        """
        if hasattr(raw_msg, "usage_metadata") and raw_msg.usage_metadata:
            usage = raw_msg.usage_metadata
            input_tok = usage.get("input_tokens", 0)
            output_tok = usage.get("output_tokens", 0)
            total_tok = usage.get("total_tokens", 0)
            return input_tok, output_tok, total_tok

        if (
            hasattr(raw_msg, "response_metadata")
            and "token_usage" in raw_msg.response_metadata
        ):
            usage = raw_msg.response_metadata["token_usage"]
            input_tok = usage.get("prompt_tokens", 0)
            output_tok = usage.get("completion_tokens", 0)
            total_tok = usage.get("total_tokens", 0)
            return input_tok, output_tok, total_tok

        return 0, 0, 0

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
            "k": settings.top_k_chunks,  # Return multiple atomic JSON schemas so the LLM can choose
            "score_threshold": settings.similarity_threshold,
        }
        if filter_conditions:
            search_kwargs["filter"] = rest.Filter(must=filter_conditions)

        vector_store = LangchainStore.get_vector_store()
        retriever = vector_store.as_retriever(
            search_type="similarity_score_threshold", search_kwargs=search_kwargs
        )

        logger.info("Retrieving documents from Qdrant with metadata filters...")
        try:
            docs = await retriever.ainvoke(message)
            return "\n\n---\n\n".join(doc.page_content for doc in docs)
        except Exception as e:
            logger.error("Vector retrieval failed (OpenAI embeddings timeout/error): {}", str(e))
            raise AppError(
                "Semantic search is temporarily unavailable due to high API load. Please try again later.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from e

    @classmethod
    async def _rewrite_query(cls, langchain_messages: list, current_message: str) -> tuple[str, AIMessage | None]:
        """
        Rewrites the current message based on chat history to provide a standalone
        semantic search query. Resolves the 'Context Loss' problem (e.g., user just says '123').
        """
        if len(langchain_messages) <= 1:
            return current_message, None
            
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "You are an assistant. Rewrite the user's latest message into a standalone search query that captures their intent based on the conversation history. Do not answer the user, just rewrite the query."),
                MessagesPlaceholder(variable_name="chat_history"),
                ("human", "Rewrite this into a standalone intent query: {current_message}"),
            ]
        )
        llm = LLMFactory.get_gpt_4o_mini()
        chain = prompt | llm
        try:
            # Pass all messages EXCEPT the last one (which is the current message already saved in DB)
            history = langchain_messages[:-1]
            # Hard enforce a 5-second timeout so query rewriting never stalls the chat request
            response = await asyncio.wait_for(
                chain.ainvoke({"chat_history": history, "current_message": current_message}),
                timeout=5.0
            )
            return response.content.strip(), response
        except asyncio.TimeoutError:
            logger.warning("Query rewrite timed out, falling back to original message.")
            return current_message, None
        except Exception as e:
            logger.warning("Query rewrite failed, falling back to original message: {}", e)
            return current_message, None
