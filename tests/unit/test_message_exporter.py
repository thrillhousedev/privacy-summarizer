"""Tests for src/exporter/message_exporter.py"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

from src.exporter.message_exporter import MessageCollector
from src.signal.cli_wrapper import SignalCLI, SignalCLIException
from src.database.repository import DatabaseRepository


class TestMessageCollectorInit:
    """Tests for MessageCollector initialization."""

    def test_stores_dependencies(self):
        """Stores signal_cli and db_repo."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)

        collector = MessageCollector(mock_cli, mock_repo)

        assert collector.signal_cli == mock_cli
        assert collector.db_repo == mock_repo


class TestSyncGroups:
    """Tests for sync_groups method."""

    def test_syncs_groups_from_signal(self):
        """Syncs groups from Signal CLI to database."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_cli.list_groups.return_value = [
            {"id": "group-1", "name": "Group One", "description": "First group"},
            {"id": "group-2", "name": "Group Two", "description": ""},
        ]
        mock_repo = MagicMock(spec=DatabaseRepository)

        collector = MessageCollector(mock_cli, mock_repo)
        count = collector.sync_groups()

        assert count == 2
        assert mock_repo.create_group.call_count == 2

    def test_skips_groups_without_id(self):
        """Skips groups without group ID."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_cli.list_groups.return_value = [
            {"id": "group-1", "name": "Valid"},
            {"name": "No ID Group"},  # Missing id
        ]
        mock_repo = MagicMock(spec=DatabaseRepository)

        collector = MessageCollector(mock_cli, mock_repo)
        count = collector.sync_groups()

        assert count == 1


class TestReceiveAndStoreMessages:
    """Tests for receive_and_store_messages method."""

    def test_stores_new_messages(self):
        """Stores new messages to database."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_cli.receive_messages.return_value = [
            {
                "envelope": {
                    "timestamp": 1234567890000,
                    "sourceUuid": "uuid-sender",
                    "dataMessage": {
                        "message": "Hello",
                        "groupInfo": {"groupId": "group-abc"}
                    }
                }
            }
        ]
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_repo.get_group_by_id.return_value = MagicMock(group_id="group-abc")
        mock_repo.store_message.return_value = (MagicMock(id=1), True)

        collector = MessageCollector(mock_cli, mock_repo)
        total, stored = collector.receive_and_store_messages(timeout=5, max_attempts=1)

        assert stored >= 1
        mock_repo.store_message.assert_called()

    def test_deduplicates_messages(self):
        """Deduplicates messages across attempts."""
        mock_cli = MagicMock(spec=SignalCLI)
        # Same message returned twice
        mock_cli.receive_messages.return_value = [
            {
                "envelope": {
                    "timestamp": 1234567890000,
                    "sourceUuid": "uuid-sender",
                    "dataMessage": {
                        "message": "Hello",
                        "groupInfo": {"groupId": "group-abc"}
                    }
                }
            }
        ]
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_repo.get_group_by_id.return_value = MagicMock(group_id="group-abc")
        mock_repo.store_message.return_value = (MagicMock(id=1), False)  # Not new

        collector = MessageCollector(mock_cli, mock_repo)
        total, stored = collector.receive_and_store_messages(timeout=5, max_attempts=2)

        # Should only store once (deduplication)
        assert stored == 0  # Not new since DB says duplicate

    def test_skips_dm_messages(self):
        """Skips direct messages (no group)."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_cli.receive_messages.return_value = [
            {
                "envelope": {
                    "timestamp": 1234567890000,
                    "sourceUuid": "uuid-sender",
                    "dataMessage": {
                        "message": "DM message"
                        # No groupInfo = DM
                    }
                }
            }
        ]
        mock_repo = MagicMock(spec=DatabaseRepository)

        collector = MessageCollector(mock_cli, mock_repo)
        total, stored = collector.receive_and_store_messages(timeout=5, max_attempts=1)

        mock_repo.store_message.assert_not_called()

    def test_handles_cli_error(self):
        """Handles SignalCLI errors gracefully."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_cli.receive_messages.side_effect = SignalCLIException("Error")
        mock_repo = MagicMock(spec=DatabaseRepository)

        collector = MessageCollector(mock_cli, mock_repo)
        total, stored = collector.receive_and_store_messages(timeout=5, max_attempts=1)

        assert total == 0
        assert stored == 0


class TestProcessEnvelope:
    """Tests for _process_envelope method."""

    def test_processes_data_message(self):
        """Processes dataMessage correctly."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_repo.get_group_by_id.return_value = MagicMock(group_id="group-abc")
        mock_repo.store_message.return_value = (MagicMock(id=1), True)

        collector = MessageCollector(mock_cli, mock_repo)
        envelope = {
            "envelope": {
                "timestamp": 1234567890000,
                "sourceUuid": "uuid-sender",
                "dataMessage": {
                    "message": "Test message",
                    "groupInfo": {"groupId": "group-abc"}
                }
            }
        }

        result = collector._process_envelope(envelope, set())

        assert result is not None
        assert result["is_new"] is True

    def test_processes_sync_message(self):
        """Processes syncMessage.sentMessage correctly."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_repo.get_group_by_id.return_value = MagicMock(group_id="group-abc")
        mock_repo.store_message.return_value = (MagicMock(id=1), True)

        collector = MessageCollector(mock_cli, mock_repo)
        envelope = {
            "envelope": {
                "timestamp": 1234567890000,
                "sourceUuid": "uuid-self",
                "syncMessage": {
                    "sentMessage": {
                        "message": "Synced message",
                        "groupInfo": {"groupId": "group-abc"}
                    }
                }
            }
        }

        result = collector._process_envelope(envelope, set())

        assert result is not None

    def test_skips_envelope_without_data_message(self):
        """Skips envelopes without data/sync message."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)

        collector = MessageCollector(mock_cli, mock_repo)
        envelope = {
            "envelope": {
                "timestamp": 1234567890000,
                "sourceUuid": "uuid-sender"
                # No dataMessage or syncMessage
            }
        }

        result = collector._process_envelope(envelope, set())

        assert result is None


class TestProcessReaction:
    """Tests for _process_reaction method."""

    def test_stores_reaction(self):
        """Stores reaction to database."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)

        # Setup message to react to
        mock_message = MagicMock()
        mock_message.id = 42
        mock_message.signal_timestamp = 1234567890000
        mock_repo.get_messages_for_group.return_value = [mock_message]
        mock_repo.store_reaction.return_value = (MagicMock(), True)

        collector = MessageCollector(mock_cli, mock_repo)

        reaction_data = {
            "emoji": "👍",
            "targetSentTimestamp": 1234567890000,
            "targetAuthorUuid": "uuid-author"
        }

        result = collector._process_reaction(
            reaction=reaction_data,
            reactor_id="uuid-reactor",
            timestamp_ms=1234567891000,
            group_id="group-abc",
            seen_keys=set()
        )

        assert result is not None
        assert result["is_new"] is True
        mock_repo.store_reaction.assert_called_once()

    def test_skips_reaction_without_target(self):
        """Skips reaction if target message not found."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_repo.get_messages_for_group.return_value = []  # No messages

        collector = MessageCollector(mock_cli, mock_repo)

        reaction_data = {
            "emoji": "👍",
            "targetSentTimestamp": 1234567890000
        }

        result = collector._process_reaction(
            reaction=reaction_data,
            reactor_id="uuid-reactor",
            timestamp_ms=1234567891000,
            group_id="group-abc",
            seen_keys=set()
        )

        assert result is None


class TestGetMessagesForSummary:
    """Tests for get_messages_for_summary method."""

    def test_filters_by_time_window(self):
        """Filters messages by time window."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_repo.get_messages_for_group.return_value = [MagicMock(), MagicMock()]

        collector = MessageCollector(mock_cli, mock_repo)
        messages = collector.get_messages_for_summary("group-abc", hours=24)

        assert len(messages) == 2
        # Verify since parameter was passed
        call_args = mock_repo.get_messages_for_group.call_args
        assert call_args[0][0] == "group-abc"
        assert call_args[1]["since"] is not None


class TestAutoRetentionFromSignal:
    """Tests for auto-retention from Signal's expiresInSeconds."""

    def test_auto_retention_from_signal_expiry(self):
        """Sets retention from expiresInSeconds when > 0."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_repo.get_group_by_id.return_value = MagicMock(group_id="group-abc")
        mock_repo.store_message.return_value = (MagicMock(id=1), True)
        mock_repo.get_group_settings.return_value = None  # No settings = use Signal
        mock_repo.get_group_retention_hours.return_value = 48  # Current default

        collector = MessageCollector(mock_cli, mock_repo)

        # 1 week = 604800 seconds = 168 hours
        data_message = {
            "message": "Test message",
            "groupInfo": {"groupId": "group-abc"},
            "expiresInSeconds": 604800
        }

        collector._process_message(
            data_message=data_message,
            sender_id="uuid-sender",
            timestamp_ms=1234567890000,
            group_id="group-abc",
            seen_keys=set()
        )

        # Should set retention to 168 hours (1 week)
        mock_repo.set_group_retention_hours.assert_called_once_with(
            "group-abc", 168, source="signal"
        )

    def test_auto_retention_default_no_expiry(self):
        """Sets 48h default when expiresInSeconds is 0."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_repo.get_group_by_id.return_value = MagicMock(group_id="group-abc")
        mock_repo.store_message.return_value = (MagicMock(id=1), True)
        mock_repo.get_group_settings.return_value = None  # No settings
        mock_repo.get_group_retention_hours.return_value = 168  # Different from default

        collector = MessageCollector(mock_cli, mock_repo)

        # No disappearing messages
        data_message = {
            "message": "Test message",
            "groupInfo": {"groupId": "group-abc"},
            "expiresInSeconds": 0
        }

        collector._process_message(
            data_message=data_message,
            sender_id="uuid-sender",
            timestamp_ms=1234567890000,
            group_id="group-abc",
            seen_keys=set()
        )

        # Should set retention to 48h default
        mock_repo.set_group_retention_hours.assert_called_once_with(
            "group-abc", 48, source="signal"
        )

    def test_auto_retention_skipped_source_command(self):
        """Preserves user-set retention when source is 'command'."""
        mock_cli = MagicMock(spec=SignalCLI)
        mock_repo = MagicMock(spec=DatabaseRepository)
        mock_repo.get_group_by_id.return_value = MagicMock(group_id="group-abc")
        mock_repo.store_message.return_value = (MagicMock(id=1), True)

        # User explicitly set retention via !retention command
        mock_settings = MagicMock()
        mock_settings.source = "command"
        mock_settings.retention_hours = 72
        mock_repo.get_group_settings.return_value = mock_settings

        collector = MessageCollector(mock_cli, mock_repo)

        # Signal has 1 week expiry, but user overrode with !retention
        data_message = {
            "message": "Test message",
            "groupInfo": {"groupId": "group-abc"},
            "expiresInSeconds": 604800  # 1 week
        }

        collector._process_message(
            data_message=data_message,
            sender_id="uuid-sender",
            timestamp_ms=1234567890000,
            group_id="group-abc",
            seen_keys=set()
        )

        # Should NOT update retention - user's choice is preserved
        mock_repo.set_group_retention_hours.assert_not_called()
