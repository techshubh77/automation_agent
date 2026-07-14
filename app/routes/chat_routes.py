from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.rate_limiter import limiter
from app.controllers.chat_controller import ChatController
from app.schemas.chat_schema import ChatRequestSchema

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/")
@limiter.limit("50/minute")
async def chat_with_agent(
    request: Request, data: ChatRequestSchema, db: AsyncSession = Depends(get_db)
):
    """
    Simple, secure chat endpoint that validates incoming JSON and generates a response from OpenAI.
    """
    return await ChatController.chat(data, db)


@router.get("/history/{org_id}")
async def index(
    org_id: str, 
    search: str | None = None,
    limit: int = 10,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    return await ChatController.index(org_id, db, search, limit, offset)


@router.get("/conversation/{conversation_id}")
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    return await ChatController.get_conversation(conversation_id, db)
