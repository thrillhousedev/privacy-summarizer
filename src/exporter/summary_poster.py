"""Post privacy-focused summaries to Signal groups - Privacy Summarizer.

Updated to use database-backed message storage instead of transient processing.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from ..ai.summarizer import ChatSummarizer
from ..signal.cli_wrapper import SignalCLI
from ..database.repository import DatabaseRepository
from ..database.models import Message
from ..utils.message_utils import split_long_message
from .message_exporter import MessageCollector

logger = logging.getLogger(__name__)


class SummaryPoster:
    """Generate and post privacy-focused summaries to Signal groups.

    Now uses database-backed message storage for reliable multi-group support.
    """

    def __init__(
        self,
        signal_cli: SignalCLI,
        chat_summarizer: ChatSummarizer,
        db_repo: DatabaseRepository,
        message_collector: MessageCollector
    ):
        """Initialize the summary poster.

        Args:
            signal_cli: SignalCLI instance for sending messages
            chat_summarizer: ChatSummarizer for generating privacy-focused summaries
            db_repo: DatabaseRepository for message storage and schedule management
            message_collector: MessageCollector for receiving and storing messages
        """
        self.signal_cli = signal_cli
        self.chat_summarizer = chat_summarizer
        self.db_repo = db_repo
        self.message_collector = message_collector

    def generate_and_post_summary(
        self,
        schedule_id: int,
        scheduled_time: str,
        dry_run: bool = False
    ) -> bool:
        """Generate a privacy-focused summary and post it to the target group.

        Uses database-backed messages for reliable summarization.

        Args:
            schedule_id: Database ID of the scheduled summary
            scheduled_time: The scheduled time that triggered this (for logging)
            dry_run: If True, print summary to console instead of posting to Signal

        Returns:
            True if successful, False otherwise
        """
        # Create a summary run record to track this execution
        summary_run = self.db_repo.create_summary_run(schedule_id=schedule_id)

        try:
            # Get the scheduled summary configuration
            schedule = self.db_repo.get_scheduled_summary_by_id(schedule_id)
            if not schedule:
                logger.error(f"Scheduled summary {schedule_id} not found")
                self.db_repo.fail_summary_run(summary_run.id, "Schedule not found")
                return False

            if not schedule.enabled:
                logger.info(f"Scheduled summary '{schedule.name}' is disabled, skipping")
                self.db_repo.fail_summary_run(summary_run.id, "Schedule disabled")
                return False

            logger.info(
                f"Generating summary for '{schedule.name}' "
                f"(source: {schedule.source_group.name}, target: {schedule.target_group.name})"
            )

            # Calculate time window
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(hours=schedule.summary_period_hours)
            period_description = f"Last {schedule.summary_period_hours} hours"

            # Get messages from database with reaction data for AI context
            messages_with_reactions = self.db_repo.get_messages_with_reactions_for_group(
                group_id=schedule.source_group.group_id,
                since=start_time,
                until=end_time
            )

            logger.info(f"Found {len(messages_with_reactions)} messages in database for time window")

            # Check if there are any messages
            if not messages_with_reactions:
                logger.info(f"No messages found for '{schedule.name}' in the specified period")
                # Post a "no activity" message
                message_text = self._format_no_activity_message(
                    schedule.source_group.name,
                    period_description
                )
                summary_text = message_text
            else:
                # Generate the privacy-focused summary
                logger.info(f"Generating privacy summary for {len(messages_with_reactions)} messages (detail_mode={schedule.detail_mode})")

                # Summarize with privacy focus and reaction context
                # Get detail_mode from schedule (defaults to True for existing schedules)
                detail_mode = getattr(schedule, 'detail_mode', True)

                summary_data = self.chat_summarizer.summarize_transient_messages(
                    message_texts=[],  # Not used when messages_with_reactions provided
                    period_description=period_description,
                    messages_with_reactions=messages_with_reactions,
                    detail=detail_mode
                )

                # Format the summary as a message based on detail mode
                message_text = self._format_summary_message(
                    schedule.source_group.name,
                    period_description,
                    summary_data,
                    detail=detail_mode
                )
                summary_text = message_text

            # Post to the target group or print to console
            # Split long messages to fit within Signal's character limit
            message_parts = split_long_message(message_text)

            if dry_run:
                logger.info(f"DRY RUN: Would post summary to '{schedule.target_group.name}' ({len(message_parts)} part(s))")
                print("\n" + "="*80)
                print(f"DRY RUN - Summary for '{schedule.name}'")
                print("="*80)
                for i, part in enumerate(message_parts):
                    if len(message_parts) > 1:
                        print(f"\n--- Part {i+1}/{len(message_parts)} ---")
                    print(part)
                print("="*80 + "\n")
            else:
                logger.info(f"Posting summary to '{schedule.target_group.name}' ({len(message_parts)} part(s))")
                for part in message_parts:
                    try:
                        self.signal_cli.send_message(
                            recipient=None,
                            message=part,
                            group_id=schedule.target_group.group_id
                        )
                    except Exception as e:
                        logger.error(f"Failed to send summary part to group: {e}")
                    # Small delay between messages to maintain order
                    if len(message_parts) > 1:
                        time.sleep(0.5)

            # Calculate time window for summary run record
            # Since messages_with_reactions is a list of dicts, we use the time window directly
            oldest_time = start_time if messages_with_reactions else None
            newest_time = end_time if messages_with_reactions else None

            # Mark summary run as completed
            self.db_repo.complete_summary_run(
                run_id=summary_run.id,
                message_count=len(messages_with_reactions),
                oldest_message_time=oldest_time,
                newest_message_time=newest_time,
                summary_text=summary_text
            )

            # Purge messages if purge_on_summary is enabled for this group (skip in dry-run mode)
            if not dry_run and self.db_repo.get_group_purge_on_summary(schedule.source_group.group_id):
                try:
                    purged = self.db_repo.purge_messages_for_group(
                        schedule.source_group.group_id,
                        before=end_time
                    )
                    logger.info(f"Purged {purged} messages after scheduled summary")
                except Exception as e:
                    logger.error(f"Failed to purge messages after scheduled summary: {e}")
            elif not dry_run:
                logger.info("Skipping post-summary purge (purge_on_summary=False)")

            # Update last_run timestamp on schedule (skip in dry-run mode)
            if not dry_run:
                self.db_repo.update_scheduled_summary_last_run(
                    schedule_id=schedule_id,
                    last_run=end_time
                )

            if dry_run:
                logger.info(f"DRY RUN: Successfully generated summary for '{schedule.name}'")
            else:
                logger.info(f"Successfully posted summary for '{schedule.name}'")

            return True

        except Exception as e:
            logger.error(f"Error generating/posting summary for schedule {schedule_id}: {e}", exc_info=True)
            self.db_repo.fail_summary_run(summary_run.id, str(e))
            return False

    def resend_summary(self, run_id: int, dry_run: bool = False) -> bool:
        """Resend a previously generated summary.

        Args:
            run_id: Database ID of the summary run to resend
            dry_run: If True, print to console instead of sending

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the summary run
            runs = self.db_repo.get_recent_summary_runs(limit=100)
            run = next((r for r in runs if r.id == run_id), None)

            if not run:
                logger.error(f"Summary run {run_id} not found")
                return False

            if not run.summary_text:
                logger.error(f"Summary run {run_id} has no stored summary text")
                return False

            schedule = run.schedule
            if not schedule:
                logger.error(f"Schedule for run {run_id} not found")
                return False

            # Split long messages to fit within Signal's character limit
            message_parts = split_long_message(run.summary_text)

            if dry_run:
                logger.info(f"DRY RUN: Would resend summary to '{schedule.target_group.name}' ({len(message_parts)} part(s))")
                print("\n" + "="*80)
                print(f"DRY RUN - Resending summary for '{schedule.name}'")
                print("="*80)
                for i, part in enumerate(message_parts):
                    if len(message_parts) > 1:
                        print(f"\n--- Part {i+1}/{len(message_parts)} ---")
                    print(part)
                print("="*80 + "\n")
            else:
                logger.info(f"Resending summary to '{schedule.target_group.name}' ({len(message_parts)} part(s))")
                for part in message_parts:
                    try:
                        self.signal_cli.send_message(
                            recipient=None,
                            message=part,
                            group_id=schedule.target_group.group_id
                        )
                    except Exception as e:
                        logger.error(f"Failed to resend summary part to group: {e}")
                    # Small delay between messages to maintain order
                    if len(message_parts) > 1:
                        time.sleep(0.5)
                logger.info(f"Successfully resent summary for '{schedule.name}'")

            return True

        except Exception as e:
            logger.error(f"Error resending summary run {run_id}: {e}", exc_info=True)
            return False

    def _get_top_emojis(self, emoji_counts: Dict[str, int], limit: int = 3) -> List[Dict[str, Any]]:
        """Get the top N most used emojis.

        Args:
            emoji_counts: Dict mapping emoji to count
            limit: Maximum number of emojis to return

        Returns:
            List of dicts with 'emoji' and 'count' keys
        """
        sorted_emojis = sorted(
            emoji_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limit]
        return [{'emoji': e, 'count': c} for e, c in sorted_emojis]

    def _format_summary_message(
        self,
        source_group_name: str,
        period_description: str,
        summary_data: Dict[str, Any],
        detail: bool = True
    ) -> str:
        """Format a summary message for Signal (plain text, no markdown).

        Args:
            source_group_name: Name of the source group
            period_description: Human-readable period description
            summary_data: Dictionary containing summary information
            detail: If True, include all stats and action items; if False, compact format

        Returns:
            Formatted message string
        """
        lines = [
            f"📊 Summary: {source_group_name}",
            f"⏰ {period_description}",
            "",
        ]

        if detail:
            # Detailed mode: show all stats on separate lines
            if "message_count" in summary_data:
                lines.append(f"💬 Messages: {summary_data['message_count']}")

            if "participant_count" in summary_data:
                lines.append(f"👥 Participants: {summary_data['participant_count']}")

            if "sentiment" in summary_data:
                sentiment_emoji = {
                    "positive": "😊",
                    "negative": "😞",
                    "neutral": "😐",
                    "mixed": "🤔"
                }.get(summary_data["sentiment"].lower(), "")
                lines.append(f"💭 Sentiment: {sentiment_emoji} {summary_data['sentiment'].title()}")

            lines.append("")
        else:
            # Simple mode: compact stats on one line
            stats_parts = []
            if "message_count" in summary_data:
                stats_parts.append(f"{summary_data['message_count']} messages")
            if "participant_count" in summary_data:
                stats_parts.append(f"{summary_data['participant_count']} participant(s)")
            if "sentiment" in summary_data:
                sentiment_emoji = {
                    "positive": "😊",
                    "negative": "😞",
                    "neutral": "😐",
                    "mixed": "🤔"
                }.get(summary_data["sentiment"].lower(), "")
                stats_parts.append(f"{sentiment_emoji} {summary_data['sentiment'].lower()}")

            if stats_parts:
                lines.append(f"📈 {' • '.join(stats_parts)}")
                lines.append("")

        # Topics (privacy-safe, no names or quotes)
        if "topics" in summary_data and summary_data["topics"]:
            lines.append("📋 Topics:")
            for topic in summary_data["topics"][:5]:  # Limit to top 5
                lines.append(f"  • {topic}")
            lines.append("")

        # Summary text (privacy-focused, no names or direct quotes)
        if "summary_text" in summary_data and summary_data["summary_text"]:
            lines.append("📝 Summary:")
            lines.append(summary_data["summary_text"])
            lines.append("")

        # Action items only in detail mode
        if detail and "action_items" in summary_data and summary_data["action_items"]:
            lines.append("✅ Action Items:")
            for item in summary_data["action_items"]:
                lines.append(f"  • {item}")
            lines.append("")

        # Remove trailing empty line if present
        while lines and lines[-1] == "":
            lines.pop()

        return "\n".join(lines)

    def _format_no_activity_message(
        self,
        source_group_name: str,
        period_description: str
    ) -> str:
        """Format a 'no activity' message (plain text, no markdown).

        Args:
            source_group_name: Name of the source group
            period_description: Human-readable period description

        Returns:
            Formatted message string
        """
        return f"""📊 Summary: {source_group_name}
⏰ {period_description}

💬 No messages during this period."""
