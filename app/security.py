import hmac

from fastapi import Header, HTTPException, status

from app.config import settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Simple shared-secret auth. Disabled when API_KEY is unset (local development).
    compare_digest avoids timing attacks."""
    if not settings.api_key:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Missing or invalid API key", headers={"WWW-Authenticate": "ApiKey"}
        )
