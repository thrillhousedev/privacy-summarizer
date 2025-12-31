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
        mock_client.generate.return_value = '["Project planning", "Design discussion"]'
        mock_client.analyze_sentiment.return_value = "positive"

        summarizer = ChatSummarizer(mock_client)
        messages = [
            "Let's discuss the project timeline",
            "I think we need to prioritize the API",
            "Agreed, the database migration should come first",
            "Can someone review my PR?",
            "I'll take a look this afternoon"
        ]

        result = summarizer.summarize_transient_messages(messages, "the last 24 hours")

        assert result["message_count"] == 5
        assert result["participant_count"] >= 2
        assert "sentiment" in result
        assert "topics" in result
        assert "summary_text" in result

    def test_summarize_handles_ollama_error(self):
        """Returns error state when Ollama fails."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.generate.side_effect = Exception("Connection refused")
        mock_client.analyze_sentiment.side_effect = Exception("Connection refused")

        summarizer = ChatSummarizer(mock_client)
        messages = ["Test message 1", "Test message 2"]

        result = summarizer.summarize_transient_messages(messages)

        assert result["message_count"] == 2
        assert "Unable to generate summary" in result["summary_text"]


class TestExtractPrivacyTopics:
    """Tests for _extract_privacy_topics method."""

    def test_extracts_topics_from_json(self):
        """Parses JSON array response into list."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.generate.return_value = '["Topic 1", "Topic 2", "Topic 3"]'

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_topics("Some conversation text")

        assert len(result) == 3
        assert "Topic 1" in result

    def test_respects_max_topics(self):
        """Limits topics to max_topics parameter."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.generate.return_value = '["T1", "T2", "T3", "T4", "T5", "T6"]'

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_topics("Text", max_topics=3)

        assert len(result) == 3

    def test_returns_empty_on_error(self):
        """Returns empty list on JSON parse error."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.generate.return_value = "Not valid JSON"

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_topics("Text")

        assert result == []

    def test_returns_empty_on_non_list(self):
        """Returns empty list if response is not a list."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.generate.return_value = '{"topics": ["a", "b"]}'

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_topics("Text")

        assert result == []


class TestExtractPrivacyActionItems:
    """Tests for _extract_privacy_action_items method."""

    def test_extracts_action_items_from_json(self):
        """Parses JSON array of action items."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.generate.return_value = '["Review the PR", "Schedule meeting"]'

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_action_items("Discussion about tasks")

        assert len(result) == 2
        assert "Review the PR" in result

    def test_returns_empty_on_error(self):
        """Returns empty list on parse error."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.generate.side_effect = Exception("API Error")

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._extract_privacy_action_items("Text")

        assert result == []


class TestGeneratePrivacySummary:
    """Tests for _generate_privacy_summary method."""

    def test_returns_generated_summary(self):
        """Returns the summary text from Ollama."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.generate.return_value = "The group discussed project planning and design."

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._generate_privacy_summary("Conversation text", "the last 24 hours")

        assert "project planning" in result.lower() or "group discussed" in result.lower()

    def test_returns_error_message_on_failure(self):
        """Returns error message when generation fails."""
        mock_client = MagicMock(spec=OllamaClient)
        mock_client.generate.side_effect = Exception("Timeout")

        summarizer = ChatSummarizer(mock_client)
        result = summarizer._generate_privacy_summary("Text", "today")

        assert "Unable to generate summary" in result


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


class TestEstimateParticipantCount:
    """Tests for _estimate_participant_count method."""

    def test_empty_text_returns_minimum(self):
        """Empty text returns minimum of 2."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        result = summarizer._estimate_participant_count("")

        assert result == 2

    def test_few_lines_returns_minimum(self):
        """Few lines returns minimum of 2."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        text = "Line 1\nLine 2\nLine 3"
        result = summarizer._estimate_participant_count(text)

        assert result == 2

    def test_many_lines_estimates_higher(self):
        """Many lines estimates more participants."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        # 25 lines should estimate ~5 participants (25 / 5 = 5)
        text = "\n".join([f"Message {i}" for i in range(25)])
        result = summarizer._estimate_participant_count(text)

        assert result == 5

    def test_capped_at_maximum(self):
        """Estimate is capped at 20."""
        mock_client = MagicMock(spec=OllamaClient)
        summarizer = ChatSummarizer(mock_client)

        # 200 lines would be 40, but capped at 20
        text = "\n".join([f"Message {i}" for i in range(200)])
        result = summarizer._estimate_participant_count(text)

        assert result == 20
