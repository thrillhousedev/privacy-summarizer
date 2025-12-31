"""API routes for Privacy Summarizer."""

from .schedules import router as schedules_router
from .stats import router as stats_router
from .groups import router as groups_router
from .health import router as health_router

__all__ = ['schedules_router', 'stats_router', 'groups_router', 'health_router']
