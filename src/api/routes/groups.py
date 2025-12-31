"""Groups API routes for Privacy Summarizer."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from ..auth import verify_api_key
from ..dependencies import get_db_repo, get_message_collector
from ...database.repository import DatabaseRepository
from ...exporter.message_exporter import MessageCollector

router = APIRouter(prefix="/groups", tags=["groups"])


class GroupResponse(BaseModel):
    id: int
    group_id: str
    name: str
    description: Optional[str]
    pending_messages: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GroupListResponse(BaseModel):
    groups: List[GroupResponse]
    total: int


class SyncResponse(BaseModel):
    groups_synced: int
    message: str


@router.get("", response_model=GroupListResponse)
async def list_groups(
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> GroupListResponse:
    """List all Signal groups."""
    groups = db_repo.get_all_groups()
    message_counts = db_repo.get_message_count_by_group()

    group_responses = []
    for group in groups:
        group_responses.append(GroupResponse(
            id=group.id,
            group_id=group.group_id,
            name=group.name,
            description=group.description,
            pending_messages=message_counts.get(group.group_id, 0),
            created_at=group.created_at,
            updated_at=group.updated_at
        ))

    return GroupListResponse(
        groups=group_responses,
        total=len(groups)
    )


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: str,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> GroupResponse:
    """Get a specific group by Signal group ID."""
    group = db_repo.get_group_by_id(group_id)

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Group {group_id} not found"
        )

    message_counts = db_repo.get_message_count_by_group()

    return GroupResponse(
        id=group.id,
        group_id=group.group_id,
        name=group.name,
        description=group.description,
        pending_messages=message_counts.get(group.group_id, 0),
        created_at=group.created_at,
        updated_at=group.updated_at
    )


@router.post("/sync", response_model=SyncResponse)
async def sync_groups(
    api_key: str = Depends(verify_api_key),
    message_collector: MessageCollector = Depends(get_message_collector)
) -> SyncResponse:
    """Sync groups from Signal."""
    try:
        count = message_collector.sync_groups()
        return SyncResponse(
            groups_synced=count,
            message=f"Successfully synced {count} groups from Signal"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync groups: {str(e)}"
        )
