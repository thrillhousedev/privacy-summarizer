"""FastAPI application for Privacy Summarizer.

Provides REST API for schedule management, stats, and group operations.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import schedules_router, stats_router, groups_router, health_router
from .dependencies import init_dependencies, cleanup_dependencies

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    logger.info("Starting Privacy Summarizer API...")
    init_dependencies()
    logger.info("API dependencies initialized")

    yield

    # Shutdown
    logger.info("Shutting down Privacy Summarizer API...")
    cleanup_dependencies()
    logger.info("API shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Privacy Summarizer API",
        description="REST API for managing Signal group summary schedules",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json"
    )

    # Configure CORS
    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers with /api prefix
    app.include_router(health_router, prefix="/api")
    app.include_router(groups_router, prefix="/api")
    app.include_router(schedules_router, prefix="/api")
    app.include_router(stats_router, prefix="/api")

    return app


# Create app instance
app = create_app()


def main():
    """Run the API server."""
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    log_level = os.getenv("LOG_LEVEL", "INFO").lower()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info(f"Starting Privacy Summarizer API on {host}:{port}")

    uvicorn.run(
        "src.api.main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=os.getenv("API_RELOAD", "false").lower() == "true"
    )


if __name__ == "__main__":
    main()
