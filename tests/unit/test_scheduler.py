"""Tests for src/scheduler/jobs.py"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
import os

from src.scheduler.jobs import ExportScheduler


class TestExportSchedulerInit:
    """Tests for ExportScheduler initialization."""

    def test_stores_dependencies(self):
        """Stores summary_poster and db_repo."""
        mock_poster = MagicMock()
        mock_repo = MagicMock()

        scheduler = ExportScheduler(mock_poster, mock_repo)

        assert scheduler.summary_poster == mock_poster
        assert scheduler.db_repo == mock_repo

    def test_default_config(self):
        """Uses default configuration values."""
        scheduler = ExportScheduler(MagicMock(), MagicMock())

        assert scheduler.purge_interval_hours == 1
        assert scheduler.default_message_retention_hours == 48

    def test_env_var_config(self):
        """Reads configuration from environment variables."""
        with patch.dict(os.environ, {
            'PURGE_INTERVAL_HOURS': '2',
            'DEFAULT_MESSAGE_RETENTION_HOURS': '72'
        }):
            scheduler = ExportScheduler(MagicMock(), MagicMock())

            assert scheduler.purge_interval_hours == 2
            assert scheduler.default_message_retention_hours == 72


class TestPurgeJob:
    """Tests for purge_job method."""

    def test_calls_purge_methods(self):
        """Calls message purge method."""
        mock_repo = MagicMock()
        mock_repo.get_enabled_scheduled_summaries.return_value = []
        mock_repo.get_pending_stats.return_value = {'messages_by_group': {}}

        scheduler = ExportScheduler(MagicMock(), mock_repo)
        scheduler.purge_job()

        # Verify purge expired messages was attempted (may have no groups to purge)
        mock_repo.get_enabled_scheduled_summaries.assert_called()

    def test_respects_schedule_retention(self):
        """Purges based on schedule retention_hours."""
        mock_repo = MagicMock()

        # Setup schedule with custom retention
        mock_schedule = MagicMock()
        mock_schedule.source_group = MagicMock()
        mock_schedule.source_group.group_id = "group-abc"
        mock_schedule.source_group.name = "Test Group"
        mock_schedule.retention_hours = 24

        mock_repo.get_enabled_scheduled_summaries.return_value = [mock_schedule]
        mock_repo.get_pending_stats.return_value = {'messages_by_group': {"group-abc": 10}}
        mock_repo.purge_messages_for_group.return_value = 5

        scheduler = ExportScheduler(MagicMock(), mock_repo)
        scheduler.purge_job()

        mock_repo.purge_messages_for_group.assert_called()


class TestPurgeExpiredMessages:
    """Tests for _purge_expired_messages method."""

    def test_purges_scheduled_groups(self):
        """Purges messages for groups with schedules."""
        mock_repo = MagicMock()

        mock_schedule = MagicMock()
        mock_schedule.source_group = MagicMock()
        mock_schedule.source_group.group_id = "group-1"
        mock_schedule.source_group.name = "Group 1"
        mock_schedule.retention_hours = 48

        mock_repo.get_enabled_scheduled_summaries.return_value = [mock_schedule]
        mock_repo.get_pending_stats.return_value = {'messages_by_group': {}}
        mock_repo.purge_messages_for_group.return_value = 3

        scheduler = ExportScheduler(MagicMock(), mock_repo)
        count = scheduler._purge_expired_messages()

        assert count == 3
        mock_repo.purge_messages_for_group.assert_called_once()

    def test_purges_orphan_groups(self):
        """Purges messages from groups without schedules."""
        mock_repo = MagicMock()
        mock_repo.get_enabled_scheduled_summaries.return_value = []
        mock_repo.get_pending_stats.return_value = {
            'messages_by_group': {"orphan-group": 5}
        }
        mock_repo.purge_messages_for_group.return_value = 5

        scheduler = ExportScheduler(MagicMock(), mock_repo)
        count = scheduler._purge_expired_messages()

        assert count == 5
        # Verify called with correct group_id
        mock_repo.purge_messages_for_group.assert_called_once()
        call_args = mock_repo.purge_messages_for_group.call_args
        assert call_args[0][0] == "orphan-group"
        # Verify 'before' is approximately 48 hours ago
        before_arg = call_args[1]["before"]
        expected = datetime.utcnow() - timedelta(hours=48)
        assert abs((before_arg - expected).total_seconds()) < 5


class TestScheduledSummaryJob:
    """Tests for scheduled_summary_job method."""

    def test_calls_summary_poster(self):
        """Calls summary_poster.generate_and_post_summary."""
        mock_poster = MagicMock()
        mock_poster.generate_and_post_summary.return_value = True

        scheduler = ExportScheduler(mock_poster, MagicMock())
        scheduler.scheduled_summary_job(schedule_id=1, scheduled_time="09:00")

        mock_poster.generate_and_post_summary.assert_called_once_with(
            schedule_id=1,
            scheduled_time="09:00",
            dry_run=False
        )

    def test_handles_poster_failure(self):
        """Handles failure gracefully."""
        mock_poster = MagicMock()
        mock_poster.generate_and_post_summary.return_value = False

        scheduler = ExportScheduler(mock_poster, MagicMock())
        # Should not raise
        scheduler.scheduled_summary_job(schedule_id=1, scheduled_time="09:00")

    def test_handles_exception(self):
        """Handles exceptions gracefully."""
        mock_poster = MagicMock()
        mock_poster.generate_and_post_summary.side_effect = Exception("Error")

        scheduler = ExportScheduler(mock_poster, MagicMock())
        # Should not raise
        scheduler.scheduled_summary_job(schedule_id=1, scheduled_time="09:00")


class TestLoadScheduledSummariesFromDB:
    """Tests for _load_scheduled_summaries_from_db method."""

    def test_loads_enabled_schedules(self):
        """Loads all enabled schedules."""
        mock_repo = MagicMock()

        mock_schedule = MagicMock()
        mock_schedule.id = 1
        mock_schedule.name = "Test Schedule"
        mock_schedule.timezone = "UTC"
        mock_schedule.schedule_type = "daily"
        mock_schedule.schedule_times = ["09:00"]

        mock_repo.get_enabled_scheduled_summaries.return_value = [mock_schedule]

        scheduler = ExportScheduler(MagicMock(), mock_repo)
        scheduler._load_scheduled_summaries_from_db()

        # Verify job was added
        jobs = scheduler.scheduler.get_jobs()
        assert len(jobs) >= 1


class TestAddScheduledSummaryJob:
    """Tests for _add_scheduled_summary_job method."""

    def test_adds_daily_job(self):
        """Adds job for daily schedule."""
        mock_schedule = MagicMock()
        mock_schedule.id = 1
        mock_schedule.name = "Daily Test"
        mock_schedule.timezone = "UTC"
        mock_schedule.schedule_type = "daily"
        mock_schedule.schedule_times = ["09:00", "18:00"]

        scheduler = ExportScheduler(MagicMock(), MagicMock())
        scheduler._add_scheduled_summary_job(mock_schedule)

        jobs = scheduler.scheduler.get_jobs()
        # Should have 2 jobs (one for each time)
        assert len(jobs) == 2

    def test_adds_weekly_job(self):
        """Adds job for weekly schedule."""
        mock_schedule = MagicMock()
        mock_schedule.id = 2
        mock_schedule.name = "Weekly Test"
        mock_schedule.timezone = "UTC"
        mock_schedule.schedule_type = "weekly"
        mock_schedule.schedule_day_of_week = 0  # Monday
        mock_schedule.schedule_times = ["10:00"]

        scheduler = ExportScheduler(MagicMock(), MagicMock())
        scheduler._add_scheduled_summary_job(mock_schedule)

        jobs = scheduler.scheduler.get_jobs()
        assert len(jobs) == 1

    def test_invalid_timezone_fallback(self):
        """Falls back to UTC for invalid timezone."""
        mock_schedule = MagicMock()
        mock_schedule.id = 3
        mock_schedule.name = "Invalid TZ"
        mock_schedule.timezone = "Invalid/Timezone"
        mock_schedule.schedule_type = "daily"
        mock_schedule.schedule_times = ["12:00"]

        scheduler = ExportScheduler(MagicMock(), MagicMock())
        # Should not raise
        scheduler._add_scheduled_summary_job(mock_schedule)

        jobs = scheduler.scheduler.get_jobs()
        assert len(jobs) == 1


class TestRunPurgeNow:
    """Tests for run_purge_now method."""

    def test_returns_purge_results(self):
        """Returns dict with purge counts."""
        mock_repo = MagicMock()
        mock_repo.get_enabled_scheduled_summaries.return_value = []
        mock_repo.get_pending_stats.return_value = {'messages_by_group': {}}

        scheduler = ExportScheduler(MagicMock(), mock_repo)
        result = scheduler.run_purge_now()

        assert "messages_purged" in result


class TestReloadSchedules:
    """Tests for reload_schedules method."""

    def test_removes_and_reloads(self):
        """Removes existing jobs and reloads from DB."""
        mock_repo = MagicMock()

        # First schedule
        mock_schedule1 = MagicMock()
        mock_schedule1.id = 1
        mock_schedule1.name = "Schedule 1"
        mock_schedule1.timezone = "UTC"
        mock_schedule1.schedule_type = "daily"
        mock_schedule1.schedule_times = ["09:00"]

        mock_repo.get_enabled_scheduled_summaries.return_value = [mock_schedule1]

        scheduler = ExportScheduler(MagicMock(), mock_repo)
        scheduler._load_scheduled_summaries_from_db()

        initial_job_count = len(scheduler.scheduler.get_jobs())
        assert initial_job_count >= 1

        # Simulate adding another schedule in DB
        mock_schedule2 = MagicMock()
        mock_schedule2.id = 2
        mock_schedule2.name = "Schedule 2"
        mock_schedule2.timezone = "UTC"
        mock_schedule2.schedule_type = "daily"
        mock_schedule2.schedule_times = ["18:00"]

        mock_repo.get_enabled_scheduled_summaries.return_value = [mock_schedule1, mock_schedule2]

        scheduler.reload_schedules()

        # Should now have 2 scheduled summary jobs
        jobs = [j for j in scheduler.scheduler.get_jobs() if j.id.startswith('scheduled_summary_')]
        assert len(jobs) == 2


class TestGroupSettingsPriority:
    """Tests for GroupSettings priority in purge operations."""

    def test_purge_respects_group_settings_priority(self):
        """GroupSettings takes priority over schedule retention_hours."""
        mock_repo = MagicMock()

        # Group has explicit GroupSettings with 24h retention
        mock_repo.get_all_group_retention_settings.return_value = {
            "group-abc": 24  # User set via !retention command
        }

        # Same group also has a schedule with 72h retention
        mock_schedule = MagicMock()
        mock_schedule.source_group = MagicMock()
        mock_schedule.source_group.group_id = "group-abc"
        mock_schedule.source_group.name = "Test Group"
        mock_schedule.retention_hours = 72  # Schedule says 72h

        mock_repo.get_enabled_scheduled_summaries.return_value = [mock_schedule]
        mock_repo.get_pending_stats.return_value = {'messages_by_group': {}}
        mock_repo.purge_messages_for_group.return_value = 5
        mock_repo.get_dm_user_ids.return_value = []

        scheduler = ExportScheduler(MagicMock(), mock_repo)
        scheduler._purge_expired_messages()

        # Should have been called with GroupSettings retention (24h), not schedule (72h)
        # The first call should be for the GroupSettings purge
        calls = mock_repo.purge_messages_for_group.call_args_list

        assert len(calls) >= 1
        # First call should be for group-abc with cutoff based on 24h
        first_call_group_id = calls[0][0][0]
        first_call_before = calls[0][1]["before"]

        assert first_call_group_id == "group-abc"

        # Verify cutoff is approximately 24 hours ago (not 72h)
        expected_cutoff = datetime.utcnow() - timedelta(hours=24)
        assert abs((first_call_before - expected_cutoff).total_seconds()) < 5

        # The schedule should NOT trigger a second purge for the same group
        # because processed_groups set prevents double-processing
        group_purge_calls = [c for c in calls if c[0][0] == "group-abc"]
        assert len(group_purge_calls) == 1  # Only one purge for this group
