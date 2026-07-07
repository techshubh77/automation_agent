from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.rate_limiter import limiter
from app.controllers.chat_controller import ChatController
from app.schemas.chat_schema import ChatRequestSchema, ChatResponseSchema

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/", response_model=ChatResponseSchema)
@limiter.limit("5/minute")
async def chat_with_agent(
    request: Request, data: ChatRequestSchema, db: AsyncSession = Depends(get_db)
):
    """
    Simple, secure chat endpoint that validates incoming JSON and generates a response from OpenAI.
    """
    return await ChatController.chat(data, db)
