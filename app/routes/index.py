from fastapi import APIRouter

from .chat_routes import router as chat_routes
from .dashboard_routes import router as dashboard_routes
from .ingestion_routes import router as ingestion_routes

api_router = APIRouter()

api_router.include_router(ingestion_routes)
api_router.include_router(chat_routes)
api_router.include_router(dashboard_routes)
