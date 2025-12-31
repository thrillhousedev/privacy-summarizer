"""Scheduled jobs for Privacy Summarizer.

Jobs:
- Purge: Deletes messages/summary runs that exceed their retention period
- Scheduled summaries: Generates and posts summaries at configured times

Note: Message collection happens in real-time via JSON-RPC, not via scheduled jobs.
"""

import logging
import os
import pytz
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class ExportScheduler:
    """Scheduler for Privacy Summarizer jobs.

    Manages:
    - Message and summary retention purge
    - Scheduled summary generation and posting

    Note: Message collection is handled real-time via SignalJSONRPCClient,
    not via periodic scheduler jobs.
    """

    def __init__(
        self,
        summary_poster,
        db_repo
    ):
        """Initialize scheduler with components.

        Args:
            summary_poster: SummaryPoster instance for generating/posting summaries
            db_repo: DatabaseRepository instance for data operations
        """
        self.summary_poster = summary_poster
        self.db_repo = db_repo

        self.scheduler = BackgroundScheduler()

        # Get configuration from environment
        self.purge_interval_hours = int(os.getenv('PURGE_INTERVAL_HOURS', '1'))
        self.default_message_retention_hours = int(os.getenv('DEFAULT_MESSAGE_RETENTION_HOURS', '48'))
        self.default_summary_retention_hours = int(os.getenv('DEFAULT_SUMMARY_RETENTION_HOURS', '168'))
        self.dm_retention_hours = int(os.getenv('DM_RETENTION_HOURS', '48'))

    def start(self):
        """Start the scheduler with all configured jobs."""
        logger.info("Starting Privacy Summarizer scheduler...")

        # Run startup cleanup
        self._startup_cleanup()

        # Add purge job
        self._add_purge_job()

        # Load scheduled summaries from database
        self._load_scheduled_summaries_from_db()

        self.scheduler.start()
        logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        logger.info("Stopping scheduler...")
        self.scheduler.shutdown(wait=True)
        logger.info("Scheduler stopped")

    # =========================================================================
    # Startup and System Jobs
    # =========================================================================

    def _startup_cleanup(self):
        """Run cleanup tasks on daemon startup.

        - Purge any messages that exceeded retention during downtime
        - Purge old summary runs
        """
        logger.info("Running startup cleanup...")

        try:
            # Purge messages based on per-schedule retention
            messages_purged = self._purge_expired_messages()
            logger.info(f"Startup cleanup: purged {messages_purged} expired messages")

            # Purge old summary runs
            runs_purged = self.db_repo.purge_old_summary_runs()
            logger.info(f"Startup cleanup: purged {runs_purged} old summary runs")

        except Exception as e:
            logger.error(f"Error during startup cleanup: {e}", exc_info=True)

    def _add_purge_job(self):
        """Add periodic purge job for messages and summary runs."""
        trigger = IntervalTrigger(hours=self.purge_interval_hours)

        self.scheduler.add_job(
            self.purge_job,
            trigger=trigger,
            id="purge",
            name="Retention Purge",
            replace_existing=True
        )

        logger.info(f"Added purge job (every {self.purge_interval_hours} hour(s))")

    def purge_job(self):
        """Purge expired messages and summary runs.

        Messages are purged based on their schedule's retention_hours.
        Summary runs are purged based on their own retention_hours.
        """
        try:
            logger.info("Starting retention purge...")

            # Purge expired messages
            messages_purged = self._purge_expired_messages()
            logger.info(f"Purged {messages_purged} expired messages")

            # Purge old summary runs
            runs_purged = self.db_repo.purge_old_summary_runs()
            logger.info(f"Purged {runs_purged} old summary runs")

            logger.info("Retention purge complete")

        except Exception as e:
            logger.error(f"Error in purge job: {e}", exc_info=True)

    def _purge_expired_messages(self) -> int:
        """Purge messages that exceed their retention period.

        Priority order for retention settings:
        1. Per-group settings (GroupSettings table) - set via !retention or Signal
        2. Per-schedule settings (for groups with active schedules)
        3. Global default (DEFAULT_MESSAGE_RETENTION_HOURS)

        Returns:
            Number of messages purged
        """
        total_purged = 0

        try:
            # Track which groups have been processed
            processed_groups = set()

            # 1. First, purge groups with explicit GroupSettings
            group_retention = self.db_repo.get_all_group_retention_settings()
            for group_id, retention_hours in group_retention.items():
                cutoff = datetime.utcnow() - timedelta(hours=retention_hours)
                purged = self.db_repo.purge_messages_for_group(group_id, before=cutoff)
                if purged > 0:
                    logger.debug(f"Purged {purged} messages for group (retention: {retention_hours}h)")
                total_purged += purged
                processed_groups.add(group_id)

            # 2. Purge groups with schedules (if not already processed)
            schedules = self.db_repo.get_enabled_scheduled_summaries()
            for schedule in schedules:
                group_id = schedule.source_group.group_id
                if group_id in processed_groups:
                    continue

                retention_hours = getattr(schedule, 'retention_hours', self.default_message_retention_hours)
                cutoff = datetime.utcnow() - timedelta(hours=retention_hours)

                purged = self.db_repo.purge_messages_for_group(
                    group_id=group_id,
                    before=cutoff
                )

                if purged > 0:
                    logger.debug(
                        f"Purged {purged} messages for '{schedule.source_group.name}' "
                        f"(schedule retention: {retention_hours}h)"
                    )

                total_purged += purged
                processed_groups.add(group_id)

            # 3. Purge remaining groups with global default
            all_stats = self.db_repo.get_pending_stats()
            for group_id in all_stats.get('messages_by_group', {}).keys():
                if group_id not in processed_groups:
                    cutoff = datetime.utcnow() - timedelta(hours=self.default_message_retention_hours)
                    purged = self.db_repo.purge_messages_for_group(group_id, before=cutoff)
                    total_purged += purged

            # 4. Purge expired DM messages (respecting per-user retention settings)
            dm_purged = self._purge_dm_messages_with_user_settings()
            total_purged += dm_purged

        except Exception as e:
            logger.error(f"Error purging expired messages: {e}", exc_info=True)

        return total_purged

    def _purge_dm_messages_with_user_settings(self) -> int:
        """Purge DM messages respecting per-user retention settings.

        For each user with DM messages:
        - Check if they have a custom retention setting
        - If yes, use their setting
        - If no, use the global dm_retention_hours default

        Returns:
            Total number of messages purged
        """
        total_purged = 0

        try:
            # Get all unique user IDs with DM messages
            user_ids = self.db_repo.get_dm_user_ids()

            # Get all custom retention settings
            custom_settings = self.db_repo.get_all_dm_retention_settings()

            for user_id in user_ids:
                # Get retention hours (custom or default)
                retention_hours = custom_settings.get(user_id, self.dm_retention_hours)
                cutoff = datetime.utcnow() - timedelta(hours=retention_hours)

                purged = self.db_repo.purge_dm_messages_for_user(user_id, before=cutoff)
                if purged > 0:
                    logger.info(f"Purged {purged} DM messages for {user_id[:8]}... (retention: {retention_hours}h)")
                    total_purged += purged

        except Exception as e:
            logger.error(f"Error purging DM messages: {e}", exc_info=True)

        return total_purged

    # =========================================================================
    # Scheduled Summary Jobs
    # =========================================================================

    def _load_scheduled_summaries_from_db(self):
        """Load all enabled scheduled summaries from database and add as jobs."""
        try:
            schedules = self.db_repo.get_enabled_scheduled_summaries()
            logger.info(f"Loading {len(schedules)} enabled scheduled summaries...")

            for schedule in schedules:
                try:
                    self._add_scheduled_summary_job(schedule)
                except Exception as e:
                    logger.error(f"Error adding scheduled summary '{schedule.name}': {e}")
                    continue

            logger.info(f"Successfully loaded {len(schedules)} scheduled summary jobs")

        except Exception as e:
            logger.error(f"Error loading scheduled summaries from database: {e}")

    def _add_scheduled_summary_job(self, schedule):
        """Add a scheduled summary job from database configuration.

        Args:
            schedule: ScheduledSummary database object
        """
        # Determine timezone
        try:
            tz = pytz.timezone(schedule.timezone)
        except Exception:
            logger.warning(f"Invalid timezone '{schedule.timezone}' for schedule '{schedule.name}', using UTC")
            tz = pytz.UTC

        schedule_type = getattr(schedule, 'schedule_type', 'daily')

        if schedule_type == 'weekly':
            # Weekly schedule
            day_of_week = getattr(schedule, 'schedule_day_of_week', 0)
            time_str = schedule.schedule_times[0] if schedule.schedule_times else "00:00"
            hour, minute = map(int, time_str.split(":"))

            trigger = CronTrigger(
                day_of_week=day_of_week,
                hour=hour,
                minute=minute,
                timezone=tz
            )

            job_id = f"scheduled_summary_{schedule.id}"
            self.scheduler.add_job(
                self.scheduled_summary_job,
                trigger=trigger,
                args=[schedule.id, time_str],
                id=job_id,
                name=f"Weekly Summary: {schedule.name}",
                replace_existing=True
            )

            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            day_name = day_names[day_of_week] if 0 <= day_of_week <= 6 else f"Day {day_of_week}"
            logger.info(f"Added weekly scheduled summary '{schedule.name}': {day_name}s at {time_str} {schedule.timezone}")

        else:
            # Daily schedule (default)
            for time_str in schedule.schedule_times:
                try:
                    hour, minute = map(int, time_str.split(":"))

                    trigger = CronTrigger(
                        hour=hour,
                        minute=minute,
                        timezone=tz
                    )

                    job_id = f"scheduled_summary_{schedule.id}_{time_str.replace(':', '')}"
                    self.scheduler.add_job(
                        self.scheduled_summary_job,
                        trigger=trigger,
                        args=[schedule.id, time_str],
                        id=job_id,
                        name=f"Daily Summary: {schedule.name} at {time_str}",
                        replace_existing=True
                    )

                    logger.info(f"Added daily scheduled summary '{schedule.name}' at {time_str} {schedule.timezone}")

                except Exception as e:
                    logger.error(f"Error parsing time '{time_str}' for schedule '{schedule.name}': {e}")
                    continue

    def scheduled_summary_job(self, schedule_id: int, scheduled_time: str):
        """Execute a scheduled summary job.

        Messages are retrieved from the database (collected by message_collection_job).
        Summary is generated and posted, then recorded in summary_runs.

        Args:
            schedule_id: Database ID of the scheduled summary
            scheduled_time: The scheduled time that triggered this (for logging)
        """
        try:
            logger.info(f"Executing scheduled summary {schedule_id} at {scheduled_time}")

            # Generate and post the summary (reads from database)
            success = self.summary_poster.generate_and_post_summary(
                schedule_id=schedule_id,
                scheduled_time=scheduled_time,
                dry_run=False
            )

            if success:
                logger.info(f"Successfully completed scheduled summary {schedule_id}")
            else:
                logger.error(f"Failed to complete scheduled summary {schedule_id}")

        except Exception as e:
            logger.error(f"Error in scheduled summary job {schedule_id}: {e}", exc_info=True)

    # =========================================================================
    # Manual Operations
    # =========================================================================

    def run_purge_now(self) -> dict:
        """Manually trigger retention purge.

        Returns:
            Dict with purge results
        """
        logger.info("Manual purge triggered")
        messages_purged = self._purge_expired_messages()
        runs_purged = self.db_repo.purge_old_summary_runs()

        return {
            'messages_purged': messages_purged,
            'summary_runs_purged': runs_purged
        }

    def reload_schedules(self):
        """Reload scheduled summaries from database.

        Useful after schedules are modified via API.
        """
        logger.info("Reloading scheduled summaries...")

        # Remove existing scheduled summary jobs
        for job in self.scheduler.get_jobs():
            if job.id.startswith('scheduled_summary_'):
                self.scheduler.remove_job(job.id)

        # Reload from database
        self._load_scheduled_summaries_from_db()

        logger.info("Scheduled summaries reloaded")
