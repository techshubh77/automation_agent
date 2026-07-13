from fastapi import status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.custom_exceptions import AppError
from app.schemas.chat_schema import (
    ChatRequestSchema,
    ChatResponseSchema,
    ConversationResponseSchema,
)
from app.services.chat_service import ChatService
from app.utils.logger import logger
from app.utils.response import success_response


class ChatController:
    @staticmethod
    async def chat(data: ChatRequestSchema, db: AsyncSession) -> ChatResponseSchema:
        try:
            agent_response, conversation_id = await ChatService.chat(data, db)
            response_data = ChatResponseSchema(
                conversation_id=str(conversation_id),
                reply=agent_response.reply,
                flag=agent_response.flag,
                preview=agent_response.preview,
                payload=agent_response.payload.model_dump()
                if agent_response.payload
                else None,
                missing_fields=agent_response.missing_fields,
                payload_example=agent_response.payload_example,
            ).model_dump()
            return success_response(
                message="Chat processed successfully", data=response_data
            )
        except AppError:
            raise
        except Exception as e:
            logger.error(f"Error in ChatController.chat: {e!s}")
            raise AppError(
                "Failed to process chat request due to an unexpected error",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    @staticmethod
    async def index(org_id: str, db: AsyncSession, search: str | None = None, limit: int = 10, offset: int = 0):
        try:
            history = await ChatService.index(org_id, db, search, limit, offset)
            formatted_history = jsonable_encoder(
                [ConversationResponseSchema.model_validate(c) for c in history]
            )
            return success_response(
                message="Chat history retrieved", data=formatted_history
            )
        except AppError:
            raise
        except Exception as e:
            logger.error(f"Error in ChatController.index: {e!s}")
            raise AppError(
                "Failed to get chat history due to an unexpected error",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e

    @staticmethod
    async def get_conversation(conversation_id: str, db: AsyncSession):
        try:
            conversation = await ChatService.get_conversation(conversation_id, db)
            formatted_conversation = jsonable_encoder(
                ConversationResponseSchema.model_validate(conversation)
            )
            return success_response(
                message="Conversation retrieved successfully", data=formatted_conversation
            )
        except AppError:
            raise
        except Exception as e:
            logger.error(f"Error in ChatController.get_conversation: {e!s}")
            raise AppError(
                "Failed to get conversation due to an unexpected error",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from e
