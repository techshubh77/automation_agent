from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions.custom_exceptions import AppError
from app.utils.logger import logger
from app.utils.response import error_response


def app_error_handler(request: Request, exc: AppError):
    """
    Handles our custom AppError, matching Node.js isOperational errors
    """
    logger.error(f"AppError: {exc.message} on {request.url}")
    return error_response(status_code=exc.status_code, message=exc.message)


def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """
    Handles FastAPI/Starlette built-in HTTP exceptions (e.g. 404, 401)
    """
    logger.error(f"HTTPException: {exc.detail} on {request.url}")
    return error_response(status_code=exc.status_code, message=str(exc.detail))


def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handles Pydantic validation errors
    """
    logger.error(f"ValidationError on {request.url}")
    return error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        message="Validation failed.",
        errors=exc.errors(),
    )


def global_exception_handler(request: Request, exc: Exception):
    """
    Catches all other unhandled errors
    """
    logger.exception(f"Unhandled Exception: {exc!s} on {request.url}")
    # In production, you might want to obscure the message like Node.js does
    return error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message="Something went wrong!",
    )
