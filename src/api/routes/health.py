"""Health check endpoint for Privacy Summarizer API."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from ..dependencies import get_db_repo, get_dependencies
from ...database.repository import DatabaseRepository

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str
    ollama: str
    signal_cli: str
    timestamp: datetime
    message: Optional[str] = None


@router.get("", response_model=HealthResponse)
async def health_check(
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> HealthResponse:
    """Check the health of all system components."""
    deps = get_dependencies()

    # Check database
    db_status = "ok"
    try:
        # Simple query to verify database connection
        db_repo.get_all_groups()
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Check Ollama
    ollama_status = "ok"
    try:
        if deps.ollama.is_available():
            ollama_status = "ok"
        else:
            ollama_status = "unavailable"
    except Exception as e:
        ollama_status = f"error: {str(e)}"

    # Check Signal CLI (just verify config exists)
    signal_status = "ok"
    try:
        # Basic check - this doesn't make network calls
        if deps.phone:
            signal_status = "configured"
        else:
            signal_status = "not configured"
    except Exception as e:
        signal_status = f"error: {str(e)}"

    # Overall status
    overall = "healthy"
    if "error" in db_status or db_status != "ok":
        overall = "degraded"
    if "error" in ollama_status:
        overall = "degraded"

    return HealthResponse(
        status=overall,
        database=db_status,
        ollama=ollama_status,
        signal_cli=signal_status,
        timestamp=datetime.utcnow()
    )
