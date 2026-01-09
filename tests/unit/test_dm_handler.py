"""Unit tests for DMHandler."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from src.dm.handler import DMHandler


class TestDMHandlerInit:
    """Tests for DMHandler initialization."""

    def test_init_with_defaults(self):
        """Initializes with default enabled state."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)

        assert handler.enabled is True
        assert handler.retention_hours == 48

    def test_init_with_custom_enabled(self):
        """Initializes with custom enabled state."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db, enabled=False)

        assert handler.enabled is False

    def test_init_from_env_disabled(self):
        """Reads DM_CHAT_ENABLED from environment."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        with patch.dict('os.environ', {'DM_CHAT_ENABLED': 'false'}):
            handler = DMHandler(mock_ollama, mock_signal, mock_db)

        assert handler.enabled is False


class TestIntentDetection:
    """Tests for intent detection."""

    def test_detect_chat_short_message(self):
        """Short messages default to chat."""
        handler = DMHandler(MagicMock(), MagicMock(), MagicMock())

        intent = handler._detect_intent("What's the capital of France?")

        assert intent == "chat"

    def test_detect_summarize_explicit(self):
        """Explicit summarize keywords with content trigger text summarization."""
        handler = DMHandler(MagicMock(), MagicMock(), MagicMock())

        # Short requests without content go to chat (need >100 chars for summarize_text)
        assert handler._detect_intent("summarize this text") == "chat"
        assert handler._detect_intent("TLDR please") == "chat"

        # With substantial content, trigger summarize_text
        long_content = "summarize this: " + "content " * 20
        assert handler._detect_intent(long_content) == "summarize_text"

    def test_detect_summarize_conversation(self):
        """Requests to summarize conversation trigger conversation summary."""
        handler = DMHandler(MagicMock(), MagicMock(), MagicMock())

        assert handler._detect_intent("summarize the conversation") == "summarize_conversation"
        assert handler._detect_intent("summarize our conversation") == "summarize_conversation"
        assert handler._detect_intent("summarize chat") == "summarize_conversation"

    def test_detect_summarize_long_text(self):
        """Long text with newlines triggers text summarization."""
        handler = DMHandler(MagicMock(), MagicMock(), MagicMock())

        long_text = "Line 1\n" * 200  # >1000 chars with newlines

        intent = handler._detect_intent(long_text)

        assert intent == "summarize_text"

    def test_detect_chat_long_without_newlines(self):
        """Long text without newlines defaults to chat."""
        handler = DMHandler(MagicMock(), MagicMock(), MagicMock())

        long_text = "a" * 1500  # >1000 chars but no newlines

        intent = handler._detect_intent(long_text)

        assert intent == "chat"


class TestCommands:
    """Tests for command handling."""

    def test_help_command_not_stored(self):
        """!help sends help message but does NOT store command."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!help")

        # Commands should NOT be stored (consistent with group chats)
        mock_db.store_dm_message.assert_not_called()
        # Should send help message
        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "!help" in call_args[1]['message']
        assert "!status" in call_args[1]['message']
        assert "!retention" in call_args[1]['message']

    def test_status_command_not_stored(self):
        """!status sends status message but does NOT store command."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = True
        mock_ollama.model = "mistral-nemo"
        mock_signal = MagicMock()
        mock_db = MagicMock()
        mock_db.get_dm_message_count.return_value = 5
        mock_db.get_dm_retention_hours.return_value = 48

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!status")

        # Commands should NOT be stored
        mock_db.store_dm_message.assert_not_called()
        # Should call get_dm_retention_hours
        mock_db.get_dm_retention_hours.assert_called_with("+1234567890")
        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "Status" in call_args[1]['message']
        assert "5" in call_args[1]['message']  # Message count
        assert "48" in call_args[1]['message']  # Retention hours

    def test_purge_command_not_stored(self):
        """!!!purge deletes conversation history but does NOT store command."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()
        mock_db.purge_dm_messages.return_value = 10

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!!!purge")

        # Commands should NOT be stored
        mock_db.store_dm_message.assert_not_called()
        mock_db.purge_dm_messages.assert_called_with("+1234567890")
        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "10" in call_args[1]['message']

    def test_summary_command_not_stored(self):
        """!summary summarizes and purges conversation but does NOT store command."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = True
        mock_ollama.generate.return_value = "This is a summary"
        mock_signal = MagicMock()
        mock_db = MagicMock()

        # Create mock messages (no command in history since it's not stored)
        mock_msg1 = MagicMock()
        mock_msg1.role = "user"
        mock_msg1.content = "Hello there"
        mock_msg2 = MagicMock()
        mock_msg2.role = "assistant"
        mock_msg2.content = "Hi! How can I help?"

        mock_db.get_dm_history.return_value = [mock_msg1, mock_msg2]
        mock_db.purge_dm_messages.return_value = 2

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!summary")

        # Commands should NOT be stored
        mock_db.store_dm_message.assert_not_called()
        mock_ollama.generate.assert_called()  # Now uses generate with privacy prompt
        mock_db.purge_dm_messages.assert_called_with("+1234567890")

    def test_summary_command_empty_conversation(self):
        """!summary with no content sends appropriate message."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = True
        mock_signal = MagicMock()
        mock_db = MagicMock()

        # Empty history (command not stored)
        mock_db.get_dm_history.return_value = []

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!summary")

        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "No conversation" in call_args[1]['message']


class TestRetentionCommand:
    """Tests for !retention command."""

    def test_retention_view_default(self):
        """!retention shows current retention period."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()
        mock_db.get_dm_retention_hours.return_value = 48

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!retention")

        # Command should NOT be stored
        mock_db.store_dm_message.assert_not_called()
        mock_db.get_dm_retention_hours.assert_called_with("+1234567890")
        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "48 hours" in call_args[1]['message']

    def test_retention_view_custom(self):
        """!retention shows custom retention period."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()
        mock_db.get_dm_retention_hours.return_value = 24

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!retention")

        call_args = mock_signal.send_message.call_args
        assert "24 hours" in call_args[1]['message']

    def test_retention_set_valid(self):
        """!retention 24 sets retention to 24 hours."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!retention 24")

        # Command should NOT be stored
        mock_db.store_dm_message.assert_not_called()
        mock_db.set_dm_retention_hours.assert_called_with("+1234567890", 24)
        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "24 hours" in call_args[1]['message']

    def test_retention_set_minimum(self):
        """!retention 1 sets retention to minimum 1 hour."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!retention 1")

        mock_db.set_dm_retention_hours.assert_called_with("+1234567890", 1)

    def test_retention_set_maximum(self):
        """!retention 168 sets retention to maximum 168 hours (7 days)."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!retention 168")

        mock_db.set_dm_retention_hours.assert_called_with("+1234567890", 168)

    def test_retention_set_too_low(self):
        """!retention 0 rejects value below minimum."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!retention 0")

        mock_db.set_dm_retention_hours.assert_not_called()
        call_args = mock_signal.send_message.call_args
        assert "Invalid" in call_args[1]['message']

    def test_retention_set_too_high(self):
        """!retention 200 rejects value above maximum."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!retention 200")

        mock_db.set_dm_retention_hours.assert_not_called()
        call_args = mock_signal.send_message.call_args
        assert "Invalid" in call_args[1]['message']
        assert "1" in call_args[1]['message']
        assert "168" in call_args[1]['message']

    def test_retention_set_invalid_string(self):
        """!retention abc rejects non-numeric value."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!retention abc")

        mock_db.set_dm_retention_hours.assert_not_called()
        call_args = mock_signal.send_message.call_args
        assert "Invalid" in call_args[1]['message']


class TestKillSwitch:
    """Tests for kill switch behavior."""

    def test_disabled_still_stores_message(self):
        """Disabled handler still stores user messages."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db, enabled=False)
        handler.handle_dm("+1234567890", "Hello!")

        # Should still store the message
        mock_db.store_dm_message.assert_called_with(
            "+1234567890", "user", "Hello!", None
        )

    def test_disabled_sends_acknowledgment(self):
        """Disabled handler sends acknowledgment message."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db, enabled=False)
        handler.handle_dm("+1234567890", "Hello!")

        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "paused" in call_args[1]['message'].lower()

    def test_disabled_commands_still_work(self):
        """Commands work even when disabled."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db, enabled=False)
        handler.handle_dm("+1234567890", "!help")

        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        # Should get help message, not "paused" message
        assert "!help" in call_args[1]['message']


class TestOllamaOffline:
    """Tests for Ollama offline behavior."""

    def test_ollama_offline_stores_message(self):
        """Offline Ollama still stores user messages."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = False
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "Hello!")

        mock_db.store_dm_message.assert_called()

    def test_ollama_offline_sends_acknowledgment(self):
        """Offline Ollama sends acknowledgment message."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = False
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "Hello!")

        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "offline" in call_args[1]['message'].lower()


class TestChat:
    """Tests for chat functionality."""

    def test_chat_uses_history(self):
        """Chat includes conversation history."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = True
        mock_ollama.chat.return_value = "I'm doing well, thanks!"
        mock_signal = MagicMock()
        mock_db = MagicMock()

        # Create mock history
        mock_msg1 = MagicMock()
        mock_msg1.role = "user"
        mock_msg1.content = "Hi there"
        mock_msg2 = MagicMock()
        mock_msg2.role = "assistant"
        mock_msg2.content = "Hello! How can I help?"
        mock_msg3 = MagicMock()
        mock_msg3.role = "user"
        mock_msg3.content = "How are you?"

        mock_db.get_dm_history.return_value = [mock_msg1, mock_msg2, mock_msg3]

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "How are you?")

        # Check that chat was called with history
        mock_ollama.chat.assert_called()
        call_args = mock_ollama.chat.call_args
        messages = call_args[0][0]

        # Should have system prompt + history
        assert messages[0]['role'] == 'system'
        assert len(messages) >= 4  # system + 3 history messages

    def test_chat_stores_response(self):
        """Chat stores assistant response."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = True
        mock_ollama.chat.return_value = "The capital is Paris."
        mock_signal = MagicMock()
        mock_db = MagicMock()
        mock_db.get_dm_history.return_value = []

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "What's the capital of France?")

        # Should store both user message and response
        calls = mock_db.store_dm_message.call_args_list
        assert len(calls) == 2

        # First call - user message
        assert calls[0][0][1] == "user"

        # Second call - assistant response
        assert calls[1][0][1] == "assistant"
        assert calls[1][0][2] == "The capital is Paris."


class TestSummarization:
    """Tests for summarization requests."""

    def test_summarize_request(self):
        """Summarize request calls generate with privacy prompt."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = True
        mock_ollama.generate.return_value = "This is a summary."
        mock_signal = MagicMock()
        mock_db = MagicMock()
        mock_db.get_dm_history.return_value = []

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        long_text = "Please summarize this:\n\n" + "Some content. " * 50

        handler.handle_dm("+1234567890", long_text)

        mock_ollama.generate.assert_called()  # Now uses generate with privacy prompt


class TestSetEnabled:
    """Tests for set_enabled method."""

    def test_set_enabled_true(self):
        """set_enabled(True) enables the handler."""
        handler = DMHandler(MagicMock(), MagicMock(), MagicMock(), enabled=False)

        handler.set_enabled(True)

        assert handler.enabled is True

    def test_set_enabled_false(self):
        """set_enabled(False) disables the handler."""
        handler = DMHandler(MagicMock(), MagicMock(), MagicMock(), enabled=True)

        handler.set_enabled(False)

        assert handler.enabled is False


class TestSummarizeCommand:
    """Tests for !summarize command (inline text summarization)."""

    def test_summarize_with_text_calls_ollama(self):
        """!summarize with text calls Ollama and returns summary."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = True
        mock_ollama.chat.return_value = "This is a summary of the text."
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!summarize This is some text that needs to be summarized for testing purposes.")

        # Command should NOT be stored
        mock_db.store_dm_message.assert_not_called()
        # Ollama chat should be called
        mock_ollama.chat.assert_called_once()
        # Response should be sent
        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "Summary" in call_args[1]['message']

    def test_summarize_without_text_returns_error(self):
        """!summarize without text returns error message."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!summarize")

        # Command should NOT be stored
        mock_db.store_dm_message.assert_not_called()
        # Ollama should NOT be called
        mock_ollama.chat.assert_not_called()
        # Error message should be sent
        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "provide text" in call_args[1]['message'].lower()

    def test_summarize_with_short_text_returns_error(self):
        """!summarize with text <20 chars returns error."""
        mock_ollama = MagicMock()
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!summarize short")

        # Ollama should NOT be called
        mock_ollama.chat.assert_not_called()
        # Error message should be sent
        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "provide text" in call_args[1]['message'].lower()

    def test_summarize_when_ollama_offline(self):
        """!summarize returns error when Ollama is offline."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = False
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!summarize This is some text that needs to be summarized for testing purposes.")

        # Ollama chat should NOT be called
        mock_ollama.chat.assert_not_called()
        # Error message should be sent
        mock_signal.send_message.assert_called()
        call_args = mock_signal.send_message.call_args
        assert "offline" in call_args[1]['message'].lower()

    def test_summarize_uses_privacy_prompt(self):
        """!summarize uses the privacy system prompt."""
        mock_ollama = MagicMock()
        mock_ollama.is_available.return_value = True
        mock_ollama.chat.return_value = "Summary text"
        mock_signal = MagicMock()
        mock_db = MagicMock()

        handler = DMHandler(mock_ollama, mock_signal, mock_db)
        handler.handle_dm("+1234567890", "!summarize This is some text that needs to be summarized for testing purposes.")

        # Check that chat was called with system message containing privacy rules
        call_args = mock_ollama.chat.call_args
        messages = call_args.kwargs.get('messages') or call_args[0][0]
        system_message = next((m for m in messages if m['role'] == 'system'), None)
        assert system_message is not None
        assert "privacy" in system_message['content'].lower() or "NEVER" in system_message['content']
