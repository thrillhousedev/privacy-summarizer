"""Tests for src/ai/summarizer.py"""

import pytest
from unittest.mock import patch, MagicMock
import json

from src.ai.summarizer import ChatSummarizer
from src.ai.ollama_client import OllamaClient


class TestChatSummarizerInit:
    """Tests for ChatSummarizer initialization."""

    def test_accepts_ollama_client(self):
        """Stores the provided OllamaClient."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)
        assert summarizer.ollama == mock_client


class TestSummarizeTransientMessages:
    """Tests for summarize_transient_messages method."""

    def test_empty_messages_returns_empty_state(self):
        """Empty message list returns zero counts and no activity message."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        result = summarizer.summarize_transient_messages([])

        assert result["message_count"] == 0
        assert result["participant_count"] == 0
        assert "No activity" in result["summary_text"]

    def test_summarize_success(self):
        """Returns full summary dict with all fields on success."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = '["Project planning", "Design discussion"]'
        mock_client.analyze_sentiment.return_value = "positive"

        summarizer = ChatSummarizer(mock_client)
        messages_with_reactions = [
            {'content': "Let's discuss the project timeline", 'sender_uuid': 'uuid-1', 'reaction_count': 0, 'emojis': []},
            {'content': "I think we need to prioritize the API", 'sender_uuid': 'uuid-2', 'reaction_count': 0, 'emojis': []},
            {'content': "Agreed, the database migration should come first", 'sender_uuid': 'uuid-3', 'reaction_count': 0, 'emojis': []},
            {'content': "Can someone review my PR?", 'sender_uuid': 'uuid-2', 'reaction_count': 0, 'emojis': []},
            {'content': "I'll take a look this afternoon", 'sender_uuid': 'uuid-1', 'reaction_count': 0, 'emojis': []},
        ]

        result = summarizer.summarize_transient_messages(
            message_texts=[],
            period_description="the last 24 hours",
            messages_with_reactions=messages_with_reactions
        )

        assert result["message_count"] == 5
        assert result["participant_count"] == 3  # uuid-1, uuid-2, uuid-3
        assert "sentiment" in result
        assert "topics" in result
        assert "summary_text" in result

    def test_insufficient_messages_returns_early(self):
        """Returns early with canned response when fewer than 5 messages."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        messages_with_reactions = [
            {'content': 'Message 1', 'sender_uuid': 'uuid-1', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 2', 'sender_uuid': 'uuid-2', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 3', 'sender_uuid': 'uuid-3', 'reaction_count': 0, 'emojis': []},
        ]

        result = summarizer.summarize_transient_messages(
            message_texts=[],
            messages_with_reactions=messages_with_reactions
        )

        assert result["message_count"] == 3
        assert result["participant_count"] == 3
        assert "Not enough messages" in result["summary_text"]
        assert result["topics"] == []
        assert result["action_items"] == []
        # Verify Ollama was NOT called
        mock_client.chat.assert_not_called()
        mock_client.analyze_sentiment.assert_not_called()

    def test_summarize_handles_ollama_error(self):
        """Returns error state when Ollama fails."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.side_effect = Exception("Connection refused")
        mock_client.analyze_sentiment.side_effect = Exception("Connection refused")

        summarizer = ChatSummarizer(mock_client)
        messages_with_reactions = [
            {'content': 'Message 1', 'sender_uuid': 'uuid-1', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 2', 'sender_uuid': 'uuid-2', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 3', 'sender_uuid': 'uuid-3', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 4', 'sender_uuid': 'uuid-4', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 5', 'sender_uuid': 'uuid-5', 'reaction_count': 0, 'emojis': []},
        ]

        result = summarizer.summarize_transient_messages(
            message_texts=[],
            messages_with_reactions=messages_with_reactions
        )

        assert result["message_count"] == 5
        assert "Unable to generate summary" in result["summary_text"]


class TestExtractPrivacyTopics:
    """Tests for _extract_privacy_topics method."""

    def test_extracts_topics_from_json(self):
        """Parses JSON array response into list."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = '["Topic 1", "Topic 2", "Topic 3"]'

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_topics("Some conversation text")

        assert len(result) == 3
        assert "Topic 1" in result

    def test_respects_max_topics(self):
        """Limits topics to max_topics parameter."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = '["T1", "T2", "T3", "T4", "T5", "T6"]'

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_topics("Text", max_topics=3)

        assert len(result) == 3

    def test_returns_empty_on_error(self):
        """Returns empty list on JSON parse error."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = "Not valid JSON"

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_topics("Text")

        assert result == []

    def test_returns_empty_on_non_list(self):
        """Returns empty list if response is not a list."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = '{"topics": ["a", "b"]}'

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_topics("Text")

        assert result == []

    def test_uses_conversation_delimiters(self):
        """Verifies conversation text is wrapped in XML delimiters."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = '["Topic 1"]'

        summarizer = ChatSummarizer(mock_client)
        summarizer._extract_privacy_topics("Test conversation")

        # Check that chat was called with messages containing delimiters
        call_args = mock_client.chat.call_args
        messages = call_args.kwargs.get('messages') or call_args[0][0]
        user_message = next(m for m in messages if m['role'] == 'user')
        assert '<conversation>' in user_message['content']
        assert '</conversation>' in user_message['content']


class TestExtractPrivacyActionItems:
    """Tests for _extract_privacy_action_items method."""

    def test_extracts_action_items_from_json(self):
        """Parses JSON array of action items."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = '["Review the PR", "Finalize the design"]'

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_action_items("Discussion about tasks")

        assert len(result) == 2
        assert "Review the PR" in result

    def test_returns_empty_on_error(self):
        """Returns empty list on parse error."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.side_effect = Exception("API Error")

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_action_items("Text")

        assert result == []

    def test_filters_generic_action_items(self):
        """Filters out generic action items that indicate prompt leakage."""
        mock_client = MagicMock(spec=OllamaClient)
        # Simulate LLM returning a mix of real and generic items
        mock_client.chat.return_value = '["Review the PR", "Check project status", "Finalize the report", "Follow up on project"]'

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_action_items("Discussion")

        # Should filter out "Check project status" and "Follow up on project"
        assert len(result) == 2
        assert "Review the PR" in result
        assert "Finalize the report" in result
        assert not any("project status" in item.lower() for item in result)
        assert not any("follow up on project" in item.lower() for item in result)

    def test_uses_conversation_delimiters(self):
        """Verifies conversation text is wrapped in XML delimiters."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = '[]'

        summarizer = ChatSummarizer(mock_client)
        summarizer._extract_privacy_action_items("Test conversation")

        # Check that chat was called with messages containing delimiters
        call_args = mock_client.chat.call_args
        messages = call_args.kwargs.get('messages') or call_args[0][0]
        user_message = next(m for m in messages if m['role'] == 'user')
        assert '<conversation>' in user_message['content']
        assert '</conversation>' in user_message['content']


class TestGeneratePrivacySummary:
    """Tests for _generate_privacy_summary method."""

    def test_returns_generated_summary(self):
        """Returns the summary text from Ollama."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = "The group discussed project planning and design."

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._generate_privacy_summary("Conversation text", "the last 24 hours")

        assert "project planning" in result.lower() or "group discussed" in result.lower()

    def test_returns_error_message_on_failure(self):
        """Returns error message when generation fails."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.side_effect = Exception("Timeout")

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._generate_privacy_summary("Text", "today")

        assert "Unable to generate summary" in result

    def test_uses_conversation_delimiters(self):
        """Verifies conversation text is wrapped in XML delimiters."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = "Summary text"

        summarizer = ChatSummarizer(mock_client)
        summarizer._generate_privacy_summary("Test conversation", "the last hour")

        # Check that chat was called with messages containing delimiters
        call_args = mock_client.chat.call_args
        messages = call_args.kwargs.get('messages') or call_args[0][0]
        user_message = next(m for m in messages if m['role'] == 'user')
        assert '<conversation>' in user_message['content']
        assert '</conversation>' in user_message['content']

    def test_uses_system_prompt(self):
        """Verifies system prompt is included in chat messages."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = "Summary text"

        summarizer = ChatSummarizer(mock_client)
        summarizer._generate_privacy_summary("Test conversation", "the last hour")

        # Check that chat was called with a system message
        call_args = mock_client.chat.call_args
        messages = call_args.kwargs.get('messages') or call_args[0][0]
        system_message = next((m for m in messages if m['role'] == 'system'), None)
        assert system_message is not None
        assert "privacy" in system_message['content'].lower()


class TestValidatePrivacy:
    """Tests for _validate_privacy method."""

    def test_clean_text_passes(self):
        """Text without violations is returned unchanged."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        text = "The group discussed project planning and upcoming deadlines."
        result = summarizer._validate_privacy(text)

        assert result == text

    def test_text_with_said_logged(self):
        """Text with 'said' triggers warning but passes."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        text = "John said he would review the code."
        result = summarizer._validate_privacy(text)

        # Currently just logs warning, doesn't modify
        assert result == text

    def test_text_with_mention_logged(self):
        """Text with '@' triggers warning but passes."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        text = "@user mentioned the deadline."
        result = summarizer._validate_privacy(text)

        # Currently just logs warning, doesn't modify
        assert result == text


class TestParticipantCount:
    """Tests for distinct participant counting from sender UUIDs."""

    def test_counts_distinct_senders(self):
        """Participant count is distinct sender_uuid count."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = '["topic1"]'
        mock_client.analyze_sentiment.return_value = "neutral"
        summarizer = ChatSummarizer(mock_client)

        messages = [
            {'content': 'Message 1', 'sender_uuid': 'uuid-a', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 2', 'sender_uuid': 'uuid-b', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 3', 'sender_uuid': 'uuid-a', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 4', 'sender_uuid': 'uuid-c', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 5', 'sender_uuid': 'uuid-b', 'reaction_count': 0, 'emojis': []},
        ]

        result = summarizer.summarize_transient_messages(
            message_texts=[],
            messages_with_reactions=messages
        )

        assert result['participant_count'] == 3  # uuid-a, uuid-b, uuid-c

    def test_single_participant_insufficient_messages(self):
        """Single sender with few messages returns early."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        messages = [
            {'content': 'Message 1', 'sender_uuid': 'uuid-a', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 2', 'sender_uuid': 'uuid-a', 'reaction_count': 0, 'emojis': []},
        ]

        result = summarizer.summarize_transient_messages(
            message_texts=[],
            messages_with_reactions=messages
        )

        # Returns early due to insufficient messages, but still counts participant
        assert result['participant_count'] == 1
        assert "Not enough messages" in result['summary_text']

    def test_no_messages_returns_zero(self):
        """Empty messages returns zero participants."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        result = summarizer.summarize_transient_messages(
            message_texts=[],
            messages_with_reactions=[]
        )

        assert result['participant_count'] == 0

    def test_missing_sender_uuid_ignored(self):
        """Messages without sender_uuid are not counted."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.chat.return_value = '["topic1"]'
        mock_client.analyze_sentiment.return_value = "neutral"
        summarizer = ChatSummarizer(mock_client)

        messages = [
            {'content': 'Message 1', 'sender_uuid': 'uuid-a', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 2', 'sender_uuid': 'uuid-a', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 3', 'sender_uuid': 'uuid-a', 'reaction_count': 0, 'emojis': []},
            {'content': 'Message 4', 'reaction_count': 0, 'emojis': []},  # No sender_uuid
            {'content': 'Message 5', 'sender_uuid': None, 'reaction_count': 0, 'emojis': []},
        ]

        result = summarizer.summarize_transient_messages(
            message_texts=[],
            messages_with_reactions=messages
        )

        assert result['participant_count'] == 1  # Only uuid-a counted


class TestIsSufficientContent:
    """Tests for _is_sufficient_content method."""

    def test_returns_false_for_none(self):
        """Returns False when messages_with_reactions is None."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        assert summarizer._is_sufficient_content(None) is False

    def test_returns_false_for_empty(self):
        """Returns False when messages list is empty."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        assert summarizer._is_sufficient_content([]) is False

    def test_returns_false_below_threshold(self):
        """Returns False when fewer than 5 messages with content."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        messages = [
            {'content': 'Message 1', 'sender_uuid': 'uuid-1'},
            {'content': 'Message 2', 'sender_uuid': 'uuid-2'},
            {'content': 'Message 3', 'sender_uuid': 'uuid-3'},
            {'content': 'Message 4', 'sender_uuid': 'uuid-4'},
        ]

        assert summarizer._is_sufficient_content(messages) is False

    def test_returns_true_at_threshold(self):
        """Returns True when exactly 5 messages with content."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        messages = [
            {'content': 'Message 1', 'sender_uuid': 'uuid-1'},
            {'content': 'Message 2', 'sender_uuid': 'uuid-2'},
            {'content': 'Message 3', 'sender_uuid': 'uuid-3'},
            {'content': 'Message 4', 'sender_uuid': 'uuid-4'},
            {'content': 'Message 5', 'sender_uuid': 'uuid-5'},
        ]

        assert summarizer._is_sufficient_content(messages) is True

    def test_ignores_empty_content(self):
        """Empty content messages don't count toward threshold."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        messages = [
            {'content': 'Message 1', 'sender_uuid': 'uuid-1'},
            {'content': '', 'sender_uuid': 'uuid-2'},
            {'content': '   ', 'sender_uuid': 'uuid-3'},
            {'content': 'Message 2', 'sender_uuid': 'uuid-4'},
            {'content': 'Message 3', 'sender_uuid': 'uuid-5'},
        ]

        # Only 3 messages have actual content
        assert summarizer._is_sufficient_content(messages) is False
