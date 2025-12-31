"""Stats API routes for Privacy Summarizer."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from datetime import datetime

from ..auth import verify_api_key
from ..dependencies import get_db_repo, get_message_collector
from ...database.repository import DatabaseRepository
from ...exporter.message_exporter import MessageCollector

router = APIRouter(prefix="/stats", tags=["stats"])


class PendingStatsResponse(BaseModel):
    total_messages: int
    messages_by_group: Dict[str, int]
    oldest_message: Optional[datetime]
    newest_message: Optional[datetime]


class SummaryRunResponse(BaseModel):
    id: int
    schedule_id: int
    schedule_name: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
    message_count: int
    status: str
    error_message: Optional[str]

    class Config:
        from_attributes = True


class RecentRunsResponse(BaseModel):
    runs: List[SummaryRunResponse]
    total: int


class GroupStatsResponse(BaseModel):
    group_id: str
    group_name: str
    pending_messages: int
    total_reactions: int
    messages_with_reactions: int
    emoji_counts: Dict[str, int]


@router.get("/pending", response_model=PendingStatsResponse)
async def get_pending_stats(
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> PendingStatsResponse:
    """Get statistics about pending messages."""
    stats = db_repo.get_pending_stats()

    return PendingStatsResponse(
        total_messages=stats['total_messages'],
        messages_by_group=stats['messages_by_group'],
        oldest_message=stats['oldest_message'],
        newest_message=stats['newest_message']
    )


@router.get("/runs", response_model=RecentRunsResponse)
async def get_recent_runs(
    limit: int = 20,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> RecentRunsResponse:
    """Get recent summary runs across all schedules."""
    runs = db_repo.get_recent_summary_runs(limit=limit)

    run_responses = []
    for run in runs:
        run_responses.append(SummaryRunResponse(
            id=run.id,
            schedule_id=run.schedule_id,
            schedule_name=run.schedule.name if run.schedule else None,
            started_at=run.started_at,
            completed_at=run.completed_at,
            message_count=run.message_count,
            status=run.status,
            error_message=run.error_message
        ))

    return RecentRunsResponse(
        runs=run_responses,
        total=len(run_responses)
    )


@router.get("/groups/{group_id}", response_model=GroupStatsResponse)
async def get_group_stats(
    group_id: str,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo),
    message_collector: MessageCollector = Depends(get_message_collector)
) -> GroupStatsResponse:
    """Get detailed statistics for a specific group."""
    group = db_repo.get_group_by_id(group_id)

    if not group:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group {group_id} not found"
        )

    # Get message count
    message_counts = db_repo.get_message_count_by_group()
    pending = message_counts.get(group_id, 0)

    # Get reaction stats
    reaction_stats = message_collector.get_reaction_stats(group_id)

    return GroupStatsResponse(
        group_id=group_id,
        group_name=group.name,
        pending_messages=pending,
        total_reactions=reaction_stats['total_reactions'],
        messages_with_reactions=reaction_stats['messages_with_reactions'],
        emoji_counts=reaction_stats['emoji_counts']
    )
