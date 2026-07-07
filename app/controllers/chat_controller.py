from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions.custom_exceptions import AppError
from app.schemas.chat_schema import ChatRequestSchema
from app.services.chat_service import ChatService
from app.utils.logger import logger
from app.utils.response import success_response


class ChatController:
    @staticmethod
    async def chat(data: ChatRequestSchema, db: AsyncSession):
        try:
            # db is available if we want to save history to Postgres later
            reply = await ChatService.chat(data)

            return success_response(
                message="Chat message processed successfully",
                data={"response": reply},
                status_code=200,
            )
        except AppError:
            raise
        except Exception as e:
            logger.error(f"Error in ChatController.chat: {e!s}")
            raise AppError(
                "Failed to process chat request due to an unexpected error", 500
            ) from e
