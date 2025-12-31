"""Shared fixtures for Privacy Summarizer tests."""

import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


# Set test environment variables before imports
os.environ.setdefault('ENCRYPTION_KEY', 'test_encryption_key_16chars')
os.environ.setdefault('TIMEZONE', 'UTC')


@pytest.fixture
def sample_envelope():
    """Sample Signal message envelope."""
    return {
        "envelope": {
            "timestamp": 1234567890000,
            "sourceUuid": "uuid-123-456-789",
            "sourceNumber": "+15551234567",
            "dataMessage": {
                "timestamp": 1234567890000,
                "groupInfo": {
                    "groupId": "group-abc-123",
                    "type": "DELIVER"
                },
                "message": "Hello world"
            }
        }
    }


@pytest.fixture
def sample_sync_envelope():
    """Sample Signal sync message envelope."""
    return {
        "envelope": {
            "timestamp": 1234567890000,
            "sourceUuid": "uuid-123-456-789",
            "syncMessage": {
                "sentMessage": {
                    "timestamp": 1234567890000,
                    "groupInfo": {
                        "groupId": "group-abc-123",
                        "type": "DELIVER"
                    },
                    "message": "Synced message"
                }
            }
        }
    }


@pytest.fixture
def sample_group_invite_envelope():
    """Sample Signal group invite envelope."""
    return {
        "envelope": {
            "timestamp": 1234567890000,
            "sourceUuid": "uuid-123-456-789",
            "dataMessage": {
                "groupInfo": {
                    "groupId": "group-new-123",
                    "type": "UPDATE"
                }
            }
        }
    }


@pytest.fixture
def sample_reaction_envelope():
    """Sample Signal reaction envelope."""
    return {
        "envelope": {
            "timestamp": 1234567891000,
            "sourceUuid": "uuid-reactor-123",
            "dataMessage": {
                "groupInfo": {
                    "groupId": "group-abc-123",
                    "type": "DELIVER"
                },
                "reaction": {
                    "emoji": "👍",
                    "targetTimestamp": 1234567890000,
                    "targetAuthor": "uuid-123-456-789"
                }
            }
        }
    }


@pytest.fixture
def sample_summary_data():
    """Sample summary result from ChatSummarizer."""
    return {
        "message_count": 42,
        "participant_count": 8,
        "topics": ["Project planning", "Design discussion", "Bug fixes"],
        "sentiment": "positive",
        "summary_text": "The group discussed project planning and design. Several bug fixes were proposed.",
        "action_items": ["Review PR #123", "Schedule follow-up meeting"]
    }


@pytest.fixture
def sample_messages():
    """Sample list of message texts."""
    return [
        "Hey everyone, let's discuss the project timeline.",
        "I think we need to prioritize the API changes.",
        "Agreed. The database migration should come first.",
        "Can someone review my PR?",
        "I'll take a look at it this afternoon.",
    ]


@pytest.fixture
def mock_ollama_response():
    """Mock Ollama API response."""
    return {
        "model": "mistral-nemo",
        "response": "This is a test summary of the conversation.",
        "done": True
    }


@pytest.fixture
def mock_signal_cli():
    """Mocked SignalCLI instance."""
    mock = MagicMock()
    mock.phone_number = "+15551234567"
    mock.config_dir = "/test/signal-cli-config"
    return mock


@pytest.fixture
def long_text():
    """Generate text longer than Signal's 2000 char limit."""
    base = "This is a test sentence that will be repeated. "
    return base * 50  # ~2400 chars


@pytest.fixture
def very_long_text():
    """Generate text requiring multiple splits."""
    base = "This is a longer test paragraph with some content. "
    return base * 150  # ~7500 chars
