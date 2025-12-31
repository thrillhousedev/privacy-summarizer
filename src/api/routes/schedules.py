"""Schedules API routes for Privacy Summarizer."""

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

from ..auth import verify_api_key
from ..dependencies import get_db_repo, get_summary_poster, get_message_collector
from ...database.repository import DatabaseRepository
from ...exporter.summary_poster import SummaryPoster
from ...exporter.message_exporter import MessageCollector

router = APIRouter(prefix="/schedules", tags=["schedules"])


# Request/Response Models

class ScheduleBase(BaseModel):
    name: str
    source_group_id: int
    target_group_id: int
    schedule_times: List[str] = Field(..., description="Times in HH:MM format")
    timezone: str = "UTC"
    summary_period_hours: int = 24
    schedule_type: str = "daily"
    schedule_day_of_week: Optional[int] = None
    retention_hours: int = 48
    enabled: bool = True


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleUpdate(BaseModel):
    schedule_times: Optional[List[str]] = None
    timezone: Optional[str] = None
    summary_period_hours: Optional[int] = None
    retention_hours: Optional[int] = None
    enabled: Optional[bool] = None


class GroupInfo(BaseModel):
    id: int
    group_id: str
    name: str

    class Config:
        from_attributes = True


class ScheduleResponse(BaseModel):
    id: int
    name: str
    source_group: GroupInfo
    target_group: GroupInfo
    schedule_times: List[str]
    timezone: str
    summary_period_hours: int
    schedule_type: str
    schedule_day_of_week: Optional[int]
    retention_hours: int
    enabled: bool
    last_run: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScheduleListResponse(BaseModel):
    schedules: List[ScheduleResponse]
    total: int


class RunNowResponse(BaseModel):
    success: bool
    message: str
    schedule_name: str


class SummaryRunResponse(BaseModel):
    id: int
    started_at: datetime
    completed_at: Optional[datetime]
    message_count: int
    status: str
    summary_text: Optional[str]
    error_message: Optional[str]

    class Config:
        from_attributes = True


# Helper functions

def schedule_to_response(schedule) -> ScheduleResponse:
    """Convert a ScheduledSummary model to response format."""
    return ScheduleResponse(
        id=schedule.id,
        name=schedule.name,
        source_group=GroupInfo(
            id=schedule.source_group.id,
            group_id=schedule.source_group.group_id,
            name=schedule.source_group.name
        ),
        target_group=GroupInfo(
            id=schedule.target_group.id,
            group_id=schedule.target_group.group_id,
            name=schedule.target_group.name
        ),
        schedule_times=schedule.schedule_times,
        timezone=schedule.timezone,
        summary_period_hours=schedule.summary_period_hours,
        schedule_type=schedule.schedule_type,
        schedule_day_of_week=schedule.schedule_day_of_week,
        retention_hours=schedule.retention_hours,
        enabled=schedule.enabled,
        last_run=schedule.last_run,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at
    )


# Routes

@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    enabled_only: bool = False,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> ScheduleListResponse:
    """List all scheduled summaries."""
    if enabled_only:
        schedules = db_repo.get_enabled_scheduled_summaries()
    else:
        schedules = db_repo.get_all_scheduled_summaries()

    return ScheduleListResponse(
        schedules=[schedule_to_response(s) for s in schedules],
        total=len(schedules)
    )


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: int,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> ScheduleResponse:
    """Get a specific schedule by ID."""
    schedule = db_repo.get_scheduled_summary_by_id(schedule_id)

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found"
        )

    return schedule_to_response(schedule)


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    data: ScheduleCreate,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> ScheduleResponse:
    """Create a new scheduled summary."""
    # Validate times format
    for time_str in data.schedule_times:
        try:
            hour, minute = map(int, time_str.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError()
        except:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid time format: {time_str}. Must be HH:MM"
            )

    # Validate timezone
    import pytz
    try:
        pytz.timezone(data.timezone)
    except:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid timezone: {data.timezone}"
        )

    try:
        schedule = db_repo.create_scheduled_summary(
            name=data.name,
            source_group_id=data.source_group_id,
            target_group_id=data.target_group_id,
            schedule_times=data.schedule_times,
            timezone=data.timezone,
            summary_period_hours=data.summary_period_hours,
            schedule_type=data.schedule_type,
            schedule_day_of_week=data.schedule_day_of_week,
            retention_hours=data.retention_hours,
            enabled=data.enabled
        )

        # Reload to get relationships
        schedule = db_repo.get_scheduled_summary_by_id(schedule.id)
        return schedule_to_response(schedule)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create schedule: {str(e)}"
        )


@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: int,
    data: ScheduleUpdate,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> ScheduleResponse:
    """Update a scheduled summary."""
    schedule = db_repo.get_scheduled_summary_by_id(schedule_id)

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found"
        )

    # Build update dict from non-None values
    updates = {k: v for k, v in data.model_dump().items() if v is not None}

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No updates provided"
        )

    # Validate times if provided
    if 'schedule_times' in updates:
        for time_str in updates['schedule_times']:
            try:
                hour, minute = map(int, time_str.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError()
            except:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid time format: {time_str}"
                )

    # Validate timezone if provided
    if 'timezone' in updates:
        import pytz
        try:
            pytz.timezone(updates['timezone'])
        except:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid timezone: {updates['timezone']}"
            )

    updated = db_repo.update_scheduled_summary(schedule_id, **updates)

    # Reload to get relationships
    updated = db_repo.get_scheduled_summary_by_id(schedule_id)
    return schedule_to_response(updated)


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: int,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
):
    """Delete a scheduled summary."""
    success = db_repo.delete_scheduled_summary(schedule_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found"
        )


@router.post("/{schedule_id}/enable", response_model=ScheduleResponse)
async def enable_schedule(
    schedule_id: int,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> ScheduleResponse:
    """Enable a scheduled summary."""
    schedule = db_repo.get_scheduled_summary_by_id(schedule_id)

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found"
        )

    db_repo.update_scheduled_summary(schedule_id, enabled=True)
    schedule = db_repo.get_scheduled_summary_by_id(schedule_id)
    return schedule_to_response(schedule)


@router.post("/{schedule_id}/disable", response_model=ScheduleResponse)
async def disable_schedule(
    schedule_id: int,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> ScheduleResponse:
    """Disable a scheduled summary."""
    schedule = db_repo.get_scheduled_summary_by_id(schedule_id)

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found"
        )

    db_repo.update_scheduled_summary(schedule_id, enabled=False)
    schedule = db_repo.get_scheduled_summary_by_id(schedule_id)
    return schedule_to_response(schedule)


@router.post("/{schedule_id}/run", response_model=RunNowResponse)
async def run_schedule_now(
    schedule_id: int,
    dry_run: bool = False,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo),
    summary_poster: SummaryPoster = Depends(get_summary_poster),
    message_collector: MessageCollector = Depends(get_message_collector)
) -> RunNowResponse:
    """Run a scheduled summary immediately."""
    schedule = db_repo.get_scheduled_summary_by_id(schedule_id)

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found"
        )

    # First collect any new messages
    message_collector.receive_and_store_messages(timeout=30)

    # Run the summary
    success = summary_poster.generate_and_post_summary(
        schedule_id=schedule_id,
        scheduled_time="api-manual",
        dry_run=dry_run
    )

    if success:
        return RunNowResponse(
            success=True,
            message=f"{'Dry run' if dry_run else 'Summary'} completed successfully",
            schedule_name=schedule.name
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to run schedule '{schedule.name}'"
        )


@router.get("/{schedule_id}/runs", response_model=List[SummaryRunResponse])
async def get_schedule_runs(
    schedule_id: int,
    limit: int = 10,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo)
) -> List[SummaryRunResponse]:
    """Get recent runs for a specific schedule."""
    schedule = db_repo.get_scheduled_summary_by_id(schedule_id)

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found"
        )

    runs = db_repo.get_summary_runs_for_schedule(schedule_id, limit=limit)

    return [
        SummaryRunResponse(
            id=run.id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            message_count=run.message_count,
            status=run.status,
            summary_text=run.summary_text,
            error_message=run.error_message
        )
        for run in runs
    ]


@router.post("/{schedule_id}/runs/{run_id}/resend", response_model=RunNowResponse)
async def resend_summary(
    schedule_id: int,
    run_id: int,
    dry_run: bool = False,
    api_key: str = Depends(verify_api_key),
    db_repo: DatabaseRepository = Depends(get_db_repo),
    summary_poster: SummaryPoster = Depends(get_summary_poster)
) -> RunNowResponse:
    """Resend a previously generated summary."""
    schedule = db_repo.get_scheduled_summary_by_id(schedule_id)

    if not schedule:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Schedule {schedule_id} not found"
        )

    success = summary_poster.resend_summary(run_id=run_id, dry_run=dry_run)

    if success:
        return RunNowResponse(
            success=True,
            message=f"Summary {'dry run' if dry_run else 'resent'} successfully",
            schedule_name=schedule.name
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resend summary"
        )
