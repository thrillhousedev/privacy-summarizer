"""Tests for src/exporter/summary_poster.py"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from src.exporter.summary_poster import SummaryPoster
from src.signal.cli_wrapper import SignalCLI
from src.ai.summarizer import ChatSummarizer
from src.database.repository import DatabaseRepository
from src.exporter.message_exporter import MessageCollector


class TestSummaryPosterInit:
    """Tests for SummaryPoster initialization."""

    def test_stores_dependencies(self):
        """Stores all dependencies."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_summarizer = MagicMock(spec=ChatSummarizer)
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_collector = MagicMock(spec=MessageCollector)

        poster = SummaryPoster(mock_cli, mock_summarizer, mock_repo, mock_collector)

        assert poster.signal_cli == mock_cli
        assert poster.chat_summarizer == mock_summarizer
        assert poster.db_repo == mock_repo
        assert poster.message_collector == mock_collector


class TestGenerateAndPostSummary:
    """Tests for generate_and_post_summary method."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_summarizer = MagicMock(spec=ChatSummarizer)
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_collector = MagicMock(spec=MessageCollector)

        # Setup schedule mock
        mock_schedule = MagicMock()
        mock_schedule.id = 1
        mock_schedule.name = "Test Schedule"
        mock_schedule.enabled = True
        mock_schedule.summary_period_hours = 24
        mock_schedule.source_group = MagicMock()
        mock_schedule.source_group.name = "Source Group"
        mock_schedule.source_group.group_id = "source-group-id"
        mock_schedule.target_group = MagicMock()
        mock_schedule.target_group.name = "Target Group"
        mock_schedule.target_group.group_id = "target-group-id"

        mock_repo.get_scheduled_summary_by_id.return_value = mock_schedule
        mock_repo.create_summary_run.return_value = MagicMock(id=1)

        return {
            "cli": mock_cli,
            "summarizer": mock_summarizer,
            "repo": mock_repo,
            "collector": mock_collector,
            "schedule": mock_schedule
        }

    def test_successful_summary_with_messages(self, mock_dependencies):
        """Generates and posts summary when messages exist."""
        deps = mock_dependencies

        # Setup messages with reactions (new format)
        deps["repo"].get_messages_with_reactions_for_group.return_value = [
            {"content": "Test message", "reaction_count": 0, "emojis": []}
        ]

        # Setup summarizer response
        deps["summarizer"].summarize_transient_messages.return_value = {
            "message_count": 1,
            "participant_count": 1,
            "summary_text": "Test summary",
            "topics": ["Testing"],
            "sentiment": "positive"
        }

        poster = SummaryPoster(
            deps["cli"],
            deps["summarizer"],
            deps["repo"],
            deps["collector"]
        )

        result = poster.generate_and_post_summary(schedule_id=1, scheduled_time="09:00")

        assert result is True
        deps["cli"].send_message.assert_called()
        deps["repo"].complete_summary_run.assert_called()

    def test_no_messages_posts_no_activity(self, mock_dependencies):
        """Posts 'no activity' message when no messages."""
        deps = mock_dependencies
        deps["repo"].get_messages_with_reactions_for_group.return_value = []

        poster = SummaryPoster(
            deps["cli"],
            deps["summarizer"],
            deps["repo"],
            deps["collector"]
        )

        result = poster.generate_and_post_summary(schedule_id=1, scheduled_time="09:00")

        assert result is True
        deps["cli"].send_message.assert_called()
        # Verify "no activity" in message
        call_args = deps["cli"].send_message.call_args[1]
        assert "No messages" in call_args["message"]

    def test_dry_run_does_not_send(self, mock_dependencies):
        """Dry run prints but doesn't send."""
        deps = mock_dependencies
        deps["repo"].get_messages_with_reactions_for_group.return_value = []

        poster = SummaryPoster(
            deps["cli"],
            deps["summarizer"],
            deps["repo"],
            deps["collector"]
        )

        result = poster.generate_and_post_summary(
            schedule_id=1,
            scheduled_time="09:00",
            dry_run=True
        )

        assert result is True
        deps["cli"].send_message.assert_not_called()

    def test_disabled_schedule_fails(self, mock_dependencies):
        """Returns False for disabled schedule."""
        deps = mock_dependencies
        deps["schedule"].enabled = False

        poster = SummaryPoster(
            deps["cli"],
            deps["summarizer"],
            deps["repo"],
            deps["collector"]
        )

        result = poster.generate_and_post_summary(schedule_id=1, scheduled_time="09:00")

        assert result is False
        deps["repo"].fail_summary_run.assert_called()

    def test_schedule_not_found_fails(self, mock_dependencies):
        """Returns False when schedule not found."""
        deps = mock_dependencies
        deps["repo"].get_scheduled_summary_by_id.return_value = None

        poster = SummaryPoster(
            deps["cli"],
            deps["summarizer"],
            deps["repo"],
            deps["collector"]
        )

        result = poster.generate_and_post_summary(schedule_id=999, scheduled_time="09:00")

        assert result is False


class TestFormatSummaryMessage:
    """Tests for _format_summary_message method."""

    @pytest.fixture
    def poster(self):
        """Create a SummaryPoster with mocks."""
        return SummaryPoster(
            MagicMock(spec=SignalCLI),
            MagicMock(spec=ChatSummarizer),
            MagicMock(spec=DatabaseRepository),
            MagicMock(spec=MessageCollector)
        )

    def test_includes_all_sections(self, poster):
        """Formats all summary data sections."""
        summary_data = {
            "message_count": 42,
            "participant_count": 8,
            "topics": ["Project planning", "Bug fixes"],
            "summary_text": "The group discussed project updates.",
            "sentiment": "positive",
            "action_items": ["Review PR", "Schedule meeting"]
        }

        # detail=True shows action items
        result = poster._format_summary_message(
            "Test Group",
            "Last 24 hours",
            summary_data,
            detail=True
        )

        assert "Test Group" in result
        assert "42" in result
        assert "8" in result
        assert "Project planning" in result
        assert "Bug fixes" in result
        assert "positive" in result or "Positive" in result
        assert "Review PR" in result
        # Footer was removed (no longer asserts "Privacy Summarizer")

    def test_simple_mode_compact_stats(self, poster):
        """Simple mode shows compact stats on one line."""
        summary_data = {
            "message_count": 10,
            "participant_count": 3,
            "sentiment": "positive"
        }

        result = poster._format_summary_message(
            "Test Group",
            "Last 24 hours",
            summary_data,
            detail=False  # simple mode
        )

        # Simple mode should show compact stats
        assert "10 messages" in result
        assert "3 participant(s)" in result


class TestFormatNoActivityMessage:
    """Tests for _format_no_activity_message method."""

    def test_formats_correctly(self):
        """Formats no activity message."""
        poster = SummaryPoster(
            MagicMock(spec=SignalCLI),
            MagicMock(spec=ChatSummarizer),
            MagicMock(spec=DatabaseRepository),
            MagicMock(spec=MessageCollector)
        )

        result = poster._format_no_activity_message("Test Group", "Last 24 hours")

        assert "Test Group" in result
        assert "No messages" in result
        # Footer was removed (no longer asserts "Privacy Summarizer")


class TestGetTopEmojis:
    """Tests for _get_top_emojis method."""

    def test_returns_top_n(self):
        """Returns top N emojis by count."""
        poster = SummaryPoster(
            MagicMock(spec=SignalCLI),
            MagicMock(spec=ChatSummarizer),
            MagicMock(spec=DatabaseRepository),
            MagicMock(spec=MessageCollector)
        )

        emoji_counts = {
            "👍": 10,
            "❤️": 25,
            "😂": 5,
            "🎉": 15
        }

        result = poster._get_top_emojis(emoji_counts, limit=2)

        assert len(result) == 2
        assert result[0]["emoji"] == "❤️"
        assert result[0]["count"] == 25
        assert result[1]["emoji"] == "🎉"


### TestResendSummary removed - resend_summary method removed since summary_text is no longer stored
