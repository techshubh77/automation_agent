from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config.settings import settings

# Initialize Argon2 Password Hasher
ph = PasswordHasher()


def hash_password(password: str) -> str:
    """Hashes a plain text password using Argon2"""
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain text password against an Argon2 hash"""
    try:
        return ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False


def create_access_token(data: dict[str, Any]) -> str:
    """
    Creates a JWT token with an expiration time.
    Equivalent to jsonwebtoken.sign() in Node.js
    """
    to_encode = data.copy()

    # Set expiration time (UTC)
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expires_in_minutes)
    to_encode.update({"exp": expire})

    # Sign the token
    return jwt.encode(
        to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> dict[str, Any] | None:
    """
    Decodes and verifies a JWT token.
    Equivalent to jsonwebtoken.verify() in Node.js
    """
    try:
        return jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        return None  # Token expired
    except jwt.InvalidTokenError:
        return None  # Token invalid/tampered
