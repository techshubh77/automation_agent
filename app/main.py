from contextlib import asynccontextmanager

import secure
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config.database import engine
from app.config.rate_limiter import limiter
from app.config.settings import settings
from app.exceptions.custom_exceptions import AppError
from app.exceptions.handlers import (
    app_error_handler,
    global_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.routes.index import api_router
from app.utils.logger import logger
from langchain_core.globals import set_debug

# Enable verbose LangChain terminal logs globally
set_debug(True)

# Initialize the secure package (Helmet equivalent)
secure_headers = secure.Secure()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    This replaces the deprecated @app.on_event("startup")
    """
    logger.info(f"Starting {settings.app_name} in {settings.env} mode...")

    # Check Database connection on startup
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection successfully established.")
    except Exception as e:
        logger.critical(f"Database connection failed: {e}")
        raise

    # Validate OpenAI API Key is present before accepting any requests
    if not settings.openai_api_key:
        logger.critical(
            "OPENAI_API_KEY is not set in environment. AI features will not work."
        )
        raise RuntimeError("OPENAI_API_KEY is required to start this application.")
    logger.info("OpenAI API key validated successfully.")

    yield  # Application runs here

    # Shutdown events
    logger.info("Shutting down application...")
    await engine.dispose()
    logger.info("Database connections closed.")


# Initialize FastAPI App
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    # Automatically disable Swagger docs in production for security
    docs_url="/docs" if settings.env == "development" else None,
    redoc_url="/redoc" if settings.env == "development" else None,
    openapi_url="/openapi.json" if settings.env == "development" else None,
    lifespan=lifespan,
)


# Wire up the rate limiter
app.state.limiter = limiter

# MIDDLEWARES
app.add_middleware(SlowAPIMiddleware)

# 1. CORS Middleware
# TODO: Replace allow_origins with the actual frontend domain before production deployment.
# Using ["*"] without credentials for now since the frontend IP isn't finalized yet.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Must be False when allow_origins=["*"] — browsers reject the combination
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. GZip Compression Middleware
# Compresses responses larger than 1000 bytes
app.add_middleware(GZipMiddleware, minimum_size=1000)


# 3. Security Headers Middleware
@app.middleware("http")
async def set_secure_headers(request: Request, call_next):
    """Applies security headers to every response"""
    response = await call_next(request)
    secure_headers.set_headers(response)
    return response


# EXCEPTION HANDLERS
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ROUTES
app.include_router(api_router, prefix="/api/v1")
