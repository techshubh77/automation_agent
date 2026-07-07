from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.constants.status_codes import StatusCode
from app.exceptions.custom_exceptions import AppError
from app.utils.security import decode_access_token

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Authentication Dependency (FastAPI's version of Auth Middleware)

    Usage in a route:
    @api_router.get("/me")
    async def get_profile(current_user: dict = Depends(get_current_user)):
        return current_user
    """
    token = credentials.credentials
    payload = decode_access_token(token)

    if not payload:
        raise AppError(
            message="Invalid or expired authentication token.",
            status_code=StatusCode.UNAUTHORIZED,
        )

    return payload
