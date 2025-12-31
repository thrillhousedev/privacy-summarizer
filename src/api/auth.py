"""Simple shared secret authentication for Privacy Summarizer API."""

import os
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

# API key header name
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key() -> str:
    """Get the API secret from environment."""
    api_key = os.getenv("API_SECRET")
    if not api_key:
        raise ValueError("API_SECRET environment variable is required")
    return api_key


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """Verify the API key from request header.

    Args:
        api_key: The API key from the X-API-Key header

    Returns:
        The validated API key

    Raises:
        HTTPException: If API key is missing or invalid
    """
    expected_key = os.getenv("API_SECRET")

    # If no API_SECRET is set, allow all requests (development mode)
    if not expected_key:
        return "development"

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide X-API-Key header.",
        )

    if api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return api_key
