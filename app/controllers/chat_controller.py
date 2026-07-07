from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.custom_exceptions import AppError
from app.schemas.chat_schema import ChatRequestSchema, ChatResponseSchema
from app.services.chat_service import ChatService
from app.utils.logger import logger


class ChatController:
    @staticmethod
    async def chat(data: ChatRequestSchema, db: AsyncSession) -> ChatResponseSchema:
        try:
            reply, conversation_id = await ChatService.chat(data, db)
            return ChatResponseSchema(reply=reply, conversation_id=conversation_id)
        except AppError:
            raise
        except Exception as e:
            logger.error(f"Error in ChatController.chat: {e!s}")
            raise AppError(
                "Failed to process chat request due to an unexpected error", 500
            ) from e
