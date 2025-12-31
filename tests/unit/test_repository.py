"""Tests for src/database/repository.py"""

import os
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

# Set required env vars before import
os.environ.setdefault('ENCRYPTION_KEY', 'test_encryption_key_16chars')

from src.database.repository import DatabaseRepository


class TestDatabaseRepositoryInit:
    """Tests for DatabaseRepository initialization."""

    def test_encryption_key_required(self):
        """Raises ValueError without encryption key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
                DatabaseRepository(":memory:", encryption_key=None)

    def test_encryption_key_min_length(self):
        """Raises ValueError if key < 16 chars."""
        with pytest.raises(ValueError, match="at least 16 characters"):
            DatabaseRepository(":memory:", encryption_key="short")

    def test_valid_key_accepted(self):
        """Accepts valid encryption key."""
        repo = DatabaseRepository(":memory:", encryption_key="test_key_16_chars")
        assert repo is not None
        assert repo.encryption_key == "test_key_16_chars"


class TestGroupOperations:
    """Tests for group CRUD operations."""

    @pytest.fixture
    def repo(self):
        """Create a fresh in-memory database for each test."""
        return DatabaseRepository(":memory:", encryption_key="test_key_16_chars")

    def test_create_group(self, repo):
        """Creates a new group."""
        group = repo.create_group("group-abc-123", "Test Group", "Description")

        assert group.group_id == "group-abc-123"
        assert group.name == "Test Group"
        assert group.description == "Description"

    def test_create_group_update_existing(self, repo):
        """Updates existing group with same ID."""
        repo.create_group("group-abc-123", "Original Name")
        group = repo.create_group("group-abc-123", "Updated Name", "New Desc")

        assert group.name == "Updated Name"
        assert group.description == "New Desc"

    def test_get_group_by_id(self, repo):
        """Retrieves group by Signal group ID."""
        repo.create_group("group-xyz", "My Group")
        group = repo.get_group_by_id("group-xyz")

        assert group is not None
        assert group.name == "My Group"

    def test_get_group_by_id_not_found(self, repo):
        """Returns None for non-existent group."""
        result = repo.get_group_by_id("nonexistent")
        assert result is None

    def test_get_all_groups(self, repo):
        """Returns all groups."""
        repo.create_group("group-1", "Group 1")
        repo.create_group("group-2", "Group 2")

        groups = repo.get_all_groups()
        assert len(groups) == 2


class TestMessageOperations:
    """Tests for message CRUD operations."""

    @pytest.fixture
    def repo(self):
        """Create a fresh in-memory database for each test."""
        return DatabaseRepository(":memory:", encryption_key="test_key_16_chars")

    def test_store_message_new(self, repo):
        """Stores new message and returns (msg, True)."""
        msg, is_new = repo.store_message(
            signal_timestamp=1234567890000,
            sender_uuid="uuid-sender-123",
            group_id="group-abc",
            content="Hello world"
        )

        assert is_new is True
        assert msg.content == "Hello world"
        assert msg.signal_timestamp == 1234567890000

    def test_store_message_duplicate(self, repo):
        """Returns (existing, False) for duplicate."""
        repo.store_message(
            signal_timestamp=1234567890000,
            sender_uuid="uuid-sender-123",
            group_id="group-abc",
            content="Original"
        )

        msg, is_new = repo.store_message(
            signal_timestamp=1234567890000,
            sender_uuid="uuid-sender-123",
            group_id="group-abc",
            content="Duplicate"
        )

        assert is_new is False
        assert msg.content == "Original"

    def test_store_messages_batch(self, repo):
        """Stores multiple messages, returns new count."""
        messages = [
            {"signal_timestamp": 1000, "sender_uuid": "u1", "group_id": "g1", "content": "Msg 1"},
            {"signal_timestamp": 2000, "sender_uuid": "u2", "group_id": "g1", "content": "Msg 2"},
            {"signal_timestamp": 3000, "sender_uuid": "u1", "group_id": "g1", "content": "Msg 3"},
        ]

        count = repo.store_messages_batch(messages)
        assert count == 3

        # Store again - should return 0 (all duplicates)
        count2 = repo.store_messages_batch(messages)
        assert count2 == 0

    def test_get_messages_for_group(self, repo):
        """Retrieves messages for a specific group."""
        repo.store_message(1000, "u1", "group-a", "Message A1")
        repo.store_message(2000, "u1", "group-a", "Message A2")
        repo.store_message(3000, "u1", "group-b", "Message B1")

        messages = repo.get_messages_for_group("group-a")
        assert len(messages) == 2

    def test_get_messages_with_time_filter(self, repo):
        """Filters messages by time window."""
        # Use realistic timestamps (Dec 2024)
        # 1734100000000 = Dec 13, 2024 ~10:26 UTC
        base_ts = 1734100000000
        repo.store_message(base_ts, "u1", "g1", "Old message")
        repo.store_message(base_ts + 60000, "u1", "g1", "Middle message")  # +1 min
        repo.store_message(base_ts + 120000, "u1", "g1", "New message")   # +2 min

        # Filter for middle range (30s to 90s after base)
        since = datetime.fromtimestamp((base_ts + 30000) / 1000)
        until = datetime.fromtimestamp((base_ts + 90000) / 1000)

        messages = repo.get_messages_for_group("g1", since=since, until=until)
        assert len(messages) == 1
        assert messages[0].content == "Middle message"

    def test_purge_messages_for_group(self, repo):
        """Deletes messages older than cutoff for specific group."""
        # Store messages with different received_at times
        msg1, _ = repo.store_message(1000, "u1", "group-a", "Old")
        msg2, _ = repo.store_message(2000, "u1", "group-a", "New")

        # Manually set received_at to simulate age
        with repo.get_session() as session:
            from src.database.models import Message
            old_msg = session.query(Message).filter_by(id=msg1.id).first()
            old_msg.received_at = datetime.utcnow() - timedelta(hours=100)
            session.commit()

        # Purge messages older than 48 hours
        cutoff = datetime.utcnow() - timedelta(hours=48)
        count = repo.purge_messages_for_group("group-a", cutoff)

        assert count == 1
        remaining = repo.get_messages_for_group("group-a")
        assert len(remaining) == 1

    def test_purge_all_messages_for_group(self, repo):
        """Deletes all messages for a group."""
        repo.store_message(1000, "u1", "group-a", "Msg 1")
        repo.store_message(2000, "u1", "group-a", "Msg 2")
        repo.store_message(3000, "u1", "group-b", "Msg B")

        count = repo.purge_all_messages_for_group("group-a")

        assert count == 2
        assert len(repo.get_messages_for_group("group-a")) == 0
        assert len(repo.get_messages_for_group("group-b")) == 1


class TestReactionOperations:
    """Tests for reaction CRUD operations."""

    @pytest.fixture
    def repo(self):
        """Create a fresh in-memory database for each test."""
        return DatabaseRepository(":memory:", encryption_key="test_key_16_chars")

    def test_store_reaction_new(self, repo):
        """Stores new reaction."""
        msg, _ = repo.store_message(1000, "u1", "g1", "Target message")

        reaction, is_new = repo.store_reaction(
            message_id=msg.id,
            emoji="👍",
            reactor_uuid="reactor-uuid",
            timestamp=2000
        )

        assert is_new is True
        assert reaction.emoji == "👍"

    def test_store_reaction_duplicate_updates(self, repo):
        """Updates existing reaction from same user."""
        msg, _ = repo.store_message(1000, "u1", "g1", "Target")

        repo.store_reaction(msg.id, "👍", "reactor-1", 2000)
        reaction, is_new = repo.store_reaction(msg.id, "❤️", "reactor-1", 3000)

        assert is_new is False
        assert reaction.emoji == "❤️"


class TestScheduledSummaryOperations:
    """Tests for scheduled summary CRUD operations."""

    @pytest.fixture
    def repo(self):
        """Create a fresh in-memory database with groups."""
        repo = DatabaseRepository(":memory:", encryption_key="test_key_16_chars")
        repo.create_group("source-group", "Source Group")
        repo.create_group("target-group", "Target Group")
        return repo

    def test_create_scheduled_summary(self, repo):
        """Creates a new scheduled summary."""
        source = repo.get_group_by_id("source-group")
        target = repo.get_group_by_id("target-group")

        schedule = repo.create_scheduled_summary(
            name="Daily Digest",
            source_group_id=source.id,
            target_group_id=target.id,
            schedule_times=["09:00", "18:00"],
            timezone="America/Chicago",
            summary_period_hours=24,
            schedule_type="daily",
            retention_hours=48,
            enabled=True
        )

        assert schedule.name == "Daily Digest"
        assert schedule.schedule_times == ["09:00", "18:00"]
        assert schedule.enabled is True

    def test_get_scheduled_summary_by_name(self, repo):
        """Retrieves schedule by name."""
        source = repo.get_group_by_id("source-group")
        target = repo.get_group_by_id("target-group")

        repo.create_scheduled_summary(
            name="Test Schedule",
            source_group_id=source.id,
            target_group_id=target.id,
            schedule_times=["12:00"]
        )

        result = repo.get_scheduled_summary_by_name("Test Schedule")
        assert result is not None
        assert result.name == "Test Schedule"

    def test_update_scheduled_summary(self, repo):
        """Updates schedule fields."""
        source = repo.get_group_by_id("source-group")
        target = repo.get_group_by_id("target-group")

        schedule = repo.create_scheduled_summary(
            name="To Update",
            source_group_id=source.id,
            target_group_id=target.id,
            schedule_times=["09:00"],
            enabled=True
        )

        updated = repo.update_scheduled_summary(
            schedule.id,
            enabled=False,
            schedule_times=["10:00", "22:00"]
        )

        assert updated.enabled is False
        assert updated.schedule_times == ["10:00", "22:00"]

    def test_delete_scheduled_summary(self, repo):
        """Deletes a schedule."""
        source = repo.get_group_by_id("source-group")
        target = repo.get_group_by_id("target-group")

        schedule = repo.create_scheduled_summary(
            name="To Delete",
            source_group_id=source.id,
            target_group_id=target.id,
            schedule_times=["09:00"]
        )

        result = repo.delete_scheduled_summary(schedule.id)
        assert result is True

        # Should be gone
        assert repo.get_scheduled_summary_by_name("To Delete") is None


class TestSummaryRunOperations:
    """Tests for summary run lifecycle operations."""

    @pytest.fixture
    def repo_with_schedule(self):
        """Create database with a schedule for runs."""
        repo = DatabaseRepository(":memory:", encryption_key="test_key_16_chars")
        repo.create_group("source", "Source")
        repo.create_group("target", "Target")
        source = repo.get_group_by_id("source")
        target = repo.get_group_by_id("target")
        schedule = repo.create_scheduled_summary(
            name="Test",
            source_group_id=source.id,
            target_group_id=target.id,
            schedule_times=["12:00"]
        )
        return repo, schedule

    def test_create_summary_run(self, repo_with_schedule):
        """Creates a new summary run."""
        repo, schedule = repo_with_schedule

        run = repo.create_summary_run(schedule.id, status="pending")

        assert run.schedule_id == schedule.id
        assert run.status == "pending"
        assert run.started_at is not None

    def test_complete_summary_run(self, repo_with_schedule):
        """Marks run as completed with results."""
        repo, schedule = repo_with_schedule
        run = repo.create_summary_run(schedule.id)

        now = datetime.utcnow()
        completed = repo.complete_summary_run(
            run.id,
            message_count=42,
            oldest_message_time=now - timedelta(hours=24),
            newest_message_time=now,
            summary_text="The group discussed various topics."
        )

        assert completed.status == "completed"
        assert completed.message_count == 42
        assert completed.summary_text == "The group discussed various topics."
        assert completed.completed_at is not None

    def test_fail_summary_run(self, repo_with_schedule):
        """Marks run as failed with error."""
        repo, schedule = repo_with_schedule
        run = repo.create_summary_run(schedule.id)

        failed = repo.fail_summary_run(run.id, "Connection timeout to Ollama")

        assert failed.status == "failed"
        assert failed.error_message == "Connection timeout to Ollama"

    def test_get_summary_runs_for_schedule(self, repo_with_schedule):
        """Gets recent runs for a schedule."""
        repo, schedule = repo_with_schedule

        # Create multiple runs
        for i in range(5):
            repo.create_summary_run(schedule.id)

        runs = repo.get_summary_runs_for_schedule(schedule.id, limit=3)

        assert len(runs) == 3


class TestPendingStats:
    """Tests for pending message statistics."""

    @pytest.fixture
    def repo(self):
        return DatabaseRepository(":memory:", encryption_key="test_key_16_chars")

    def test_get_pending_stats_empty(self, repo):
        """Returns zeros when no messages."""
        stats = repo.get_pending_stats()

        assert stats["total_messages"] == 0
        assert stats["messages_by_group"] == {}

    def test_get_pending_stats_with_messages(self, repo):
        """Returns correct counts with messages."""
        repo.store_message(1000, "u1", "group-a", "Msg 1")
        repo.store_message(2000, "u1", "group-a", "Msg 2")
        repo.store_message(3000, "u1", "group-b", "Msg 3")

        stats = repo.get_pending_stats()

        assert stats["total_messages"] == 3
        assert stats["messages_by_group"]["group-a"] == 2
        assert stats["messages_by_group"]["group-b"] == 1


class TestDMRetentionSettings:
    """Tests for DM retention settings."""

    @pytest.fixture
    def repo(self):
        return DatabaseRepository(":memory:", encryption_key="test_key_16_chars")

    def test_get_dm_retention_hours_default(self, repo):
        """Returns default 48 hours when no setting exists."""
        hours = repo.get_dm_retention_hours("+1234567890")
        assert hours == 48

    def test_set_dm_retention_hours_new(self, repo):
        """Creates new setting for user."""
        repo.set_dm_retention_hours("+1234567890", 24)

        hours = repo.get_dm_retention_hours("+1234567890")
        assert hours == 24

    def test_set_dm_retention_hours_update(self, repo):
        """Updates existing setting."""
        repo.set_dm_retention_hours("+1234567890", 24)
        repo.set_dm_retention_hours("+1234567890", 72)

        hours = repo.get_dm_retention_hours("+1234567890")
        assert hours == 72

    def test_get_dm_retention_hours_per_user(self, repo):
        """Each user has their own setting."""
        repo.set_dm_retention_hours("+1111111111", 12)
        repo.set_dm_retention_hours("+2222222222", 100)

        assert repo.get_dm_retention_hours("+1111111111") == 12
        assert repo.get_dm_retention_hours("+2222222222") == 100
        assert repo.get_dm_retention_hours("+3333333333") == 48  # Default

    def test_get_all_dm_retention_settings(self, repo):
        """Gets all custom settings for purge job."""
        repo.set_dm_retention_hours("+1111111111", 12)
        repo.set_dm_retention_hours("+2222222222", 100)

        settings = repo.get_all_dm_retention_settings()

        assert settings["+1111111111"] == 12
        assert settings["+2222222222"] == 100
        assert len(settings) == 2

    def test_get_all_dm_retention_settings_empty(self, repo):
        """Returns empty dict when no custom settings."""
        settings = repo.get_all_dm_retention_settings()
        assert settings == {}


class TestDMMessageOperations:
    """Tests for DM message operations."""

    @pytest.fixture
    def repo(self):
        return DatabaseRepository(":memory:", encryption_key="test_key_16_chars")

    def test_store_dm_message(self, repo):
        """Stores a DM message."""
        msg = repo.store_dm_message("+1234567890", "user", "Hello!")

        assert msg.user_id == "+1234567890"
        assert msg.role == "user"
        assert msg.content == "Hello!"

    def test_get_dm_history(self, repo):
        """Gets DM history in order."""
        repo.store_dm_message("+1234567890", "user", "First")
        repo.store_dm_message("+1234567890", "assistant", "Response")
        repo.store_dm_message("+1234567890", "user", "Second")

        history = repo.get_dm_history("+1234567890")

        assert len(history) == 3
        assert history[0].content == "First"
        assert history[1].content == "Response"
        assert history[2].content == "Second"

    def test_get_dm_history_per_user(self, repo):
        """Each user has separate history."""
        repo.store_dm_message("+1111111111", "user", "User 1 msg")
        repo.store_dm_message("+2222222222", "user", "User 2 msg")

        history1 = repo.get_dm_history("+1111111111")
        history2 = repo.get_dm_history("+2222222222")

        assert len(history1) == 1
        assert len(history2) == 1
        assert history1[0].content == "User 1 msg"
        assert history2[0].content == "User 2 msg"

    def test_get_dm_message_count(self, repo):
        """Counts messages for a user."""
        repo.store_dm_message("+1234567890", "user", "One")
        repo.store_dm_message("+1234567890", "assistant", "Two")
        repo.store_dm_message("+1234567890", "user", "Three")

        count = repo.get_dm_message_count("+1234567890")
        assert count == 3

    def test_purge_dm_messages(self, repo):
        """Purges all messages for a user."""
        repo.store_dm_message("+1234567890", "user", "One")
        repo.store_dm_message("+1234567890", "assistant", "Two")

        count = repo.purge_dm_messages("+1234567890")

        assert count == 2
        assert repo.get_dm_message_count("+1234567890") == 0

    def test_get_dm_user_ids(self, repo):
        """Gets unique user IDs with DM messages."""
        repo.store_dm_message("+1111111111", "user", "Msg")
        repo.store_dm_message("+2222222222", "user", "Msg")
        repo.store_dm_message("+1111111111", "assistant", "Reply")

        user_ids = repo.get_dm_user_ids()

        assert len(user_ids) == 2
        assert "+1111111111" in user_ids
        assert "+2222222222" in user_ids

    def test_purge_dm_messages_for_user(self, repo):
        """Purges DM messages older than cutoff for specific user."""
        # Store messages
        msg1 = repo.store_dm_message("+1234567890", "user", "Old message")
        msg2 = repo.store_dm_message("+1234567890", "user", "New message")

        # Manually age the first message
        with repo.get_session() as session:
            from src.database.models import DMConversation
            old_msg = session.query(DMConversation).filter_by(id=msg1.id).first()
            old_msg.created_at = datetime.utcnow() - timedelta(hours=100)
            session.commit()

        # Purge messages older than 48 hours
        cutoff = datetime.utcnow() - timedelta(hours=48)
        count = repo.purge_dm_messages_for_user("+1234567890", cutoff)

        assert count == 1
        remaining = repo.get_dm_history("+1234567890")
        assert len(remaining) == 1
        assert remaining[0].content == "New message"


class TestGroupSettingsOperations:
    """Tests for group retention settings operations."""

    @pytest.fixture
    def repo(self):
        return DatabaseRepository(":memory:", encryption_key="test_key_16_chars")

    def test_get_group_retention_hours_default(self, repo):
        """Returns default 48 hours when no setting exists."""
        hours = repo.get_group_retention_hours("group-abc-123")
        assert hours == 48

    def test_set_group_retention_hours_new(self, repo):
        """Creates new setting for group."""
        repo.set_group_retention_hours("group-abc-123", 72, source="signal")

        hours = repo.get_group_retention_hours("group-abc-123")
        assert hours == 72

    def test_set_group_retention_hours_update(self, repo):
        """Updates existing setting including source."""
        repo.set_group_retention_hours("group-abc-123", 24, source="signal")
        repo.set_group_retention_hours("group-abc-123", 168, source="command")

        hours = repo.get_group_retention_hours("group-abc-123")
        assert hours == 168

        settings = repo.get_group_settings("group-abc-123")
        assert settings.source == "command"

    def test_get_group_settings_none(self, repo):
        """Returns None when no settings exist."""
        settings = repo.get_group_settings("nonexistent-group")
        assert settings is None

    def test_get_group_settings_exists(self, repo):
        """Returns GroupSettings object when settings exist."""
        repo.set_group_retention_hours("group-abc-123", 72, source="signal")

        settings = repo.get_group_settings("group-abc-123")

        assert settings is not None
        assert settings.group_id == "group-abc-123"
        assert settings.retention_hours == 72
        assert settings.source == "signal"

    def test_get_all_group_retention_settings(self, repo):
        """Gets all group settings for purge job."""
        repo.set_group_retention_hours("group-1", 24, source="signal")
        repo.set_group_retention_hours("group-2", 168, source="command")

        settings = repo.get_all_group_retention_settings()

        assert settings["group-1"] == 24
        assert settings["group-2"] == 168
        assert len(settings) == 2

    def test_get_all_group_retention_settings_empty(self, repo):
        """Returns empty dict when no settings exist."""
        settings = repo.get_all_group_retention_settings()
        assert settings == {}


class TestGroupPowerModeOperations:
    """Tests for group power mode (admin permissions) operations."""

    @pytest.fixture
    def repo(self):
        return DatabaseRepository(":memory:", encryption_key="test_key_16_chars")

    def test_get_group_power_mode_default(self, repo):
        """Returns 'admins' (default) when no setting exists."""
        mode = repo.get_group_power_mode("nonexistent-group")
        assert mode == "admins"

    def test_set_group_power_mode_new(self, repo):
        """Creates new setting for group."""
        repo.set_group_power_mode("group-abc-123", "everyone")

        mode = repo.get_group_power_mode("group-abc-123")
        assert mode == "everyone"

    def test_set_group_power_mode_update(self, repo):
        """Updates existing setting."""
        repo.set_group_power_mode("group-abc-123", "everyone")
        repo.set_group_power_mode("group-abc-123", "admins")

        mode = repo.get_group_power_mode("group-abc-123")
        assert mode == "admins"

    def test_set_group_power_mode_invalid(self, repo):
        """Raises ValueError for invalid mode."""
        with pytest.raises(ValueError, match="Invalid power mode"):
            repo.set_group_power_mode("group-abc-123", "invalid")

    def test_power_mode_preserves_retention(self, repo):
        """Setting power mode preserves existing retention settings."""
        # Set retention first
        repo.set_group_retention_hours("group-abc-123", 72, source="command")

        # Set power mode
        repo.set_group_power_mode("group-abc-123", "everyone")

        # Check retention is preserved
        hours = repo.get_group_retention_hours("group-abc-123")
        assert hours == 72

        settings = repo.get_group_settings("group-abc-123")
        assert settings.power_mode == "everyone"
        assert settings.source == "command"

    def test_power_mode_creates_with_defaults(self, repo):
        """Creating power mode also sets default retention."""
        repo.set_group_power_mode("group-abc-123", "everyone")

        settings = repo.get_group_settings("group-abc-123")
        assert settings.power_mode == "everyone"
        assert settings.retention_hours == 48  # Default
        assert settings.source == "signal"  # Default


class TestUserOptOut:
    """Tests for user opt-out operations."""

    @pytest.fixture
    def repo(self):
        """Create a fresh in-memory database for each test."""
        return DatabaseRepository(":memory:", encryption_key="test_key_16_chars")

    def test_is_user_opted_out_default_false(self, repo):
        """Default is opted-in (returns False)."""
        result = repo.is_user_opted_out("group-abc", "user-123")
        assert result is False

    def test_is_user_opted_out_after_opt_out(self, repo):
        """Returns True after user opts out."""
        repo.set_user_opt_out("group-abc", "user-123", opted_out=True)
        result = repo.is_user_opted_out("group-abc", "user-123")
        assert result is True

    def test_set_user_opt_out_creates_record(self, repo):
        """Creates new opt-out record."""
        repo.set_user_opt_out("group-abc", "user-123", opted_out=True)
        result = repo.is_user_opted_out("group-abc", "user-123")
        assert result is True

    def test_set_user_opt_out_updates_existing(self, repo):
        """Updates existing record when toggling."""
        repo.set_user_opt_out("group-abc", "user-123", opted_out=True)
        repo.set_user_opt_out("group-abc", "user-123", opted_out=False)
        result = repo.is_user_opted_out("group-abc", "user-123")
        assert result is False

    def test_opt_out_is_per_group(self, repo):
        """Opt-out in one group doesn't affect other groups."""
        repo.set_user_opt_out("group-A", "user-123", opted_out=True)

        assert repo.is_user_opted_out("group-A", "user-123") is True
        assert repo.is_user_opted_out("group-B", "user-123") is False

    def test_delete_user_messages_returns_count(self, repo):
        """Returns count of deleted messages."""
        # Create group first
        repo.create_group("group-abc", "Test Group")

        # Store some messages
        repo.store_message(1000, "user-123", "group-abc", "Message 1")
        repo.store_message(2000, "user-123", "group-abc", "Message 2")
        repo.store_message(3000, "user-456", "group-abc", "Other user")

        # Delete user-123's messages
        count = repo.delete_user_messages_in_group("group-abc", "user-123")
        assert count == 2

    def test_delete_user_messages_only_deletes_correct_user(self, repo):
        """Only deletes messages from specified user."""
        repo.create_group("group-abc", "Test Group")

        repo.store_message(1000, "user-123", "group-abc", "To delete")
        repo.store_message(2000, "user-456", "group-abc", "Keep this")

        repo.delete_user_messages_in_group("group-abc", "user-123")

        # Check remaining messages
        messages = repo.get_messages_for_group("group-abc")
        assert len(messages) == 1
        assert messages[0].sender_uuid == "user-456"

    def test_delete_user_messages_only_deletes_in_group(self, repo):
        """Only deletes messages in specified group."""
        repo.create_group("group-A", "Group A")
        repo.create_group("group-B", "Group B")

        repo.store_message(1000, "user-123", "group-A", "Delete this")
        repo.store_message(2000, "user-123", "group-B", "Keep this")

        repo.delete_user_messages_in_group("group-A", "user-123")

        # Check group-B still has the message
        messages = repo.get_messages_for_group("group-B")
        assert len(messages) == 1
