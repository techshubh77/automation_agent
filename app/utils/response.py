from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse


def success_response(
    status_code: int = status.HTTP_200_OK, message: str = "Success", data: Any | None = None
) -> JSONResponse:
    """Utility to send a standardized success response"""
    return JSONResponse(
        status_code=status_code,
        content={"status": "success", "message": message, "data": data},
    )


def error_response(
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR, message: str = "Error", errors: Any | None = None
) -> JSONResponse:
    """Utility to send a standardized error response"""
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "error" if status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR else "fail",
            "message": message,
            "errors": errors,
        },
    )
