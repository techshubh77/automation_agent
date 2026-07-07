from fastapi import APIRouter

from .chat_routes import router as chat_router
from .ingestion_routes import router as ingestion_router

api_router = APIRouter()

api_router.include_router(ingestion_router)
api_router.include_router(chat_router)
