"""Tests for src/ai/ollama_client.py"""

import pytest
from unittest.mock import patch, MagicMock
import requests

from src.ai.ollama_client import OllamaClient, OllamaException


class TestOllamaClientInit:
    """Tests for OllamaClient initialization."""

    def test_default_values(self):
        """Uses default host, model, and max_tokens."""
        client = OllamaClient()
        assert client.host == "http://localhost:11434"
        assert client.model == "mistral-nemo"
        assert client.max_input_tokens == 16000

    def test_custom_values(self):
        """Accepts custom host, model, and max_tokens."""
        client = OllamaClient(
            host="http://custom:8080/",
            model="llama2",
            max_input_tokens=8000
        )
        assert client.host == "http://custom:8080"  # Trailing slash stripped
        assert client.model == "llama2"
        assert client.max_input_tokens == 8000


class TestEstimateTokens:
    """Tests for _estimate_tokens method."""

    def test_empty_string(self):
        """Empty string returns 0 tokens."""
        client = OllamaClient()
        assert client._estimate_tokens("") == 0

    def test_short_text(self):
        """4 chars ≈ 1 token."""
        client = OllamaClient()
        assert client._estimate_tokens("test") == 1

    def test_longer_text(self):
        """Consistent estimation for longer text."""
        client = OllamaClient()
        text = "a" * 100
        assert client._estimate_tokens(text) == 25


class TestTruncateToTokens:
    """Tests for _truncate_to_tokens method."""

    def test_no_truncation_needed(self):
        """Text under limit is returned unchanged."""
        client = OllamaClient(max_input_tokens=100)
        text = "Short text"
        assert client._truncate_to_tokens(text) == text

    def test_truncation_applied(self):
        """Text over limit is truncated."""
        client = OllamaClient(max_input_tokens=10)
        text = "a" * 100  # 25 tokens estimated
        result = client._truncate_to_tokens(text)
        assert len(result) == 40  # 10 tokens * 4 chars

    def test_custom_max_tokens(self):
        """Respects custom max_tokens parameter."""
        client = OllamaClient(max_input_tokens=1000)
        text = "a" * 100
        result = client._truncate_to_tokens(text, max_tokens=5)
        assert len(result) == 20  # 5 tokens * 4 chars


class TestIsAvailable:
    """Tests for is_available method."""

    @patch('requests.get')
    def test_available(self, mock_get):
        """Returns True when Ollama responds with 200."""
        mock_get.return_value.status_code = 200
        client = OllamaClient()

        assert client.is_available() is True
        mock_get.assert_called_once_with("http://localhost:11434/", timeout=5)

    @patch('requests.get')
    def test_not_available_connection_error(self, mock_get):
        """Returns False on connection error."""
        mock_get.side_effect = requests.ConnectionError("Connection refused")
        client = OllamaClient()

        assert client.is_available() is False

    @patch('requests.get')
    def test_not_available_timeout(self, mock_get):
        """Returns False on timeout."""
        mock_get.side_effect = requests.Timeout("Request timed out")
        client = OllamaClient()

        assert client.is_available() is False

    @patch('requests.get')
    def test_not_available_non_200(self, mock_get):
        """Returns False when status code is not 200."""
        mock_get.return_value.status_code = 500
        client = OllamaClient()

        assert client.is_available() is False


class TestListModels:
    """Tests for list_models method."""

    @patch('requests.get')
    def test_success(self, mock_get):
        """Returns list of models on success."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "models": [
                {"name": "mistral-nemo"},
                {"name": "llama2"}
            ]
        }
        client = OllamaClient()

        result = client.list_models()

        assert len(result) == 2
        assert result[0]["name"] == "mistral-nemo"

    @patch('requests.get')
    def test_empty_list(self, mock_get):
        """Returns empty list when no models."""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"models": []}
        client = OllamaClient()

        result = client.list_models()

        assert result == []

    @patch('requests.get')
    def test_error_raises_exception(self, mock_get):
        """Raises OllamaException on error."""
        mock_get.side_effect = requests.ConnectionError("Connection refused")
        client = OllamaClient()

        with pytest.raises(OllamaException):
            client.list_models()


class TestGenerate:
    """Tests for generate method."""

    @patch('requests.post')
    def test_basic_generation(self, mock_post):
        """Returns generated text on success."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": "Generated response text"
        }
        client = OllamaClient()

        result = client.generate("Test prompt")

        assert result == "Generated response text"

    @patch('requests.post')
    def test_with_system_prompt(self, mock_post):
        """Includes system prompt in payload."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": "Response"}
        client = OllamaClient()

        client.generate("Test", system_prompt="System context")

        call_json = mock_post.call_args[1]["json"]
        assert call_json["system"] == "System context"

    @patch('requests.post')
    def test_with_temperature(self, mock_post):
        """Uses specified temperature."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": "Response"}
        client = OllamaClient()

        client.generate("Test", temperature=0.5)

        call_json = mock_post.call_args[1]["json"]
        assert call_json["options"]["temperature"] == 0.5

    @patch('requests.post')
    def test_error_raises_exception(self, mock_post):
        """Raises OllamaException on error."""
        mock_post.side_effect = requests.Timeout("Timeout")
        client = OllamaClient()

        with pytest.raises(OllamaException):
            client.generate("Test prompt")


class TestAnalyzeSentiment:
    """Tests for analyze_sentiment method."""

    @patch('requests.post')
    def test_positive_sentiment(self, mock_post):
        """Returns 'positive' for positive response."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": "positive"}
        client = OllamaClient()

        result = client.analyze_sentiment("I love this!")

        assert result == "positive"

    @patch('requests.post')
    def test_negative_sentiment(self, mock_post):
        """Returns 'negative' for negative response."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": "Negative"}
        client = OllamaClient()

        result = client.analyze_sentiment("This is terrible")

        assert result == "negative"

    @patch('requests.post')
    def test_invalid_response_defaults_neutral(self, mock_post):
        """Returns 'neutral' for invalid response."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": "I don't know"}
        client = OllamaClient()

        result = client.analyze_sentiment("Some text")

        assert result == "neutral"


class TestExtractTopics:
    """Tests for extract_topics method."""

    @patch('requests.post')
    def test_extracts_topics(self, mock_post):
        """Parses topics from response."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": "- Topic 1\n- Topic 2\n- Topic 3"
        }
        client = OllamaClient()

        result = client.extract_topics("Some discussion text")

        assert len(result) == 3
        assert "Topic 1" in result

    @patch('requests.post')
    def test_respects_max_topics(self, mock_post):
        """Limits topics to max_topics."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": "Topic 1\nTopic 2\nTopic 3\nTopic 4\nTopic 5\nTopic 6"
        }
        client = OllamaClient()

        result = client.extract_topics("Text", max_topics=3)

        assert len(result) <= 3

    @patch('requests.post')
    def test_cleans_formatting(self, mock_post):
        """Removes bullet points and numbers."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": "1. First topic\n2. Second topic\n• Third topic"
        }
        client = OllamaClient()

        result = client.extract_topics("Text")

        for topic in result:
            assert not topic.startswith("1.")
            assert not topic.startswith("2.")
            assert not topic.startswith("•")


class TestExtractActionItems:
    """Tests for extract_action_items method."""

    @patch('requests.post')
    def test_extracts_items(self, mock_post):
        """Parses action items from response."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": "- Review the PR\n- Schedule meeting\n- Update docs"
        }
        client = OllamaClient()

        result = client.extract_action_items("Discussion about tasks")

        assert len(result) == 3

    @patch('requests.post')
    def test_none_returns_empty(self, mock_post):
        """Returns empty list for 'None' response."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": "None"}
        client = OllamaClient()

        result = client.extract_action_items("No action items here")

        assert result == []

    @patch('requests.post')
    def test_filters_short_items(self, mock_post):
        """Filters out items shorter than 5 chars."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "response": "- Do it\n- abc\n- Review the documentation"
        }
        client = OllamaClient()

        result = client.extract_action_items("Text")

        # "abc" should be filtered, "Do it" might be edge case
        assert "abc" not in result
        assert any("documentation" in item.lower() for item in result)


class TestChat:
    """Tests for chat method."""

    @patch('requests.post')
    def test_single_message(self, mock_post):
        """Handles single message conversation."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "message": {"content": "Response from model"}
        }
        client = OllamaClient()

        messages = [{"role": "user", "content": "Hello"}]
        result = client.chat(messages)

        assert result == "Response from model"

    @patch('requests.post')
    def test_multi_turn(self, mock_post):
        """Handles multi-turn conversation."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "message": {"content": "I remember, you asked about Python."}
        }
        client = OllamaClient()

        messages = [
            {"role": "user", "content": "Tell me about Python"},
            {"role": "assistant", "content": "Python is a programming language."},
            {"role": "user", "content": "What did I ask?"}
        ]
        result = client.chat(messages)

        assert "Python" in result or "remember" in result


class TestCompareMessagesForContradictions:
    """Tests for compare_messages_for_contradictions method."""

    def test_less_than_two_groups(self):
        """Returns empty list with fewer than 2 groups."""
        client = OllamaClient()

        result = client.compare_messages_for_contradictions({
            "Group1": ["Message 1", "Message 2"]
        })

        assert result == []

    @patch('requests.post')
    def test_no_contradictions(self, mock_post):
        """Returns empty list when response is NONE."""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"response": "NONE"}
        client = OllamaClient()

        result = client.compare_messages_for_contradictions({
            "Group1": ["I'm feeling great"],
            "Group2": ["Having a good day"]
        })

        assert result == []
