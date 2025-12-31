"""Dependency injection for Privacy Summarizer API."""

import os
from functools import lru_cache
from typing import Generator

from ..database.repository import DatabaseRepository
from ..signal.cli_wrapper import SignalCLI
from ..exporter.message_exporter import MessageCollector
from ..ai.ollama_client import OllamaClient
from ..ai.summarizer import ChatSummarizer
from ..exporter.summary_poster import SummaryPoster


class AppDependencies:
    """Container for application dependencies."""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Get configuration from environment
        self.db_path = os.getenv("DB_PATH", "/data/privacy_summarizer.db")
        self.phone = os.getenv("SIGNAL_PHONE_NUMBER")
        self.config_dir = os.getenv("SIGNAL_CLI_CONFIG_DIR", "/signal-cli-config")
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "mistral-nemo")

        # Initialize core components
        self._db_repo = None
        self._signal_cli = None
        self._message_collector = None
        self._ollama = None
        self._summarizer = None
        self._summary_poster = None

    @property
    def db_repo(self) -> DatabaseRepository:
        if self._db_repo is None:
            self._db_repo = DatabaseRepository(self.db_path)
        return self._db_repo

    @property
    def signal_cli(self) -> SignalCLI:
        if self._signal_cli is None:
            if not self.phone:
                raise ValueError("SIGNAL_PHONE_NUMBER environment variable is required")
            self._signal_cli = SignalCLI(self.phone, self.config_dir)
        return self._signal_cli

    @property
    def message_collector(self) -> MessageCollector:
        if self._message_collector is None:
            self._message_collector = MessageCollector(self.signal_cli, self.db_repo)
        return self._message_collector

    @property
    def ollama(self) -> OllamaClient:
        if self._ollama is None:
            self._ollama = OllamaClient(self.ollama_host, self.ollama_model)
        return self._ollama

    @property
    def summarizer(self) -> ChatSummarizer:
        if self._summarizer is None:
            self._summarizer = ChatSummarizer(self.ollama)
        return self._summarizer

    @property
    def summary_poster(self) -> SummaryPoster:
        if self._summary_poster is None:
            self._summary_poster = SummaryPoster(
                self.signal_cli,
                self.summarizer,
                self.db_repo,
                self.message_collector
            )
        return self._summary_poster


@lru_cache()
def get_dependencies() -> AppDependencies:
    """Get the singleton application dependencies."""
    return AppDependencies()


def get_db_repo() -> DatabaseRepository:
    """Dependency for database repository."""
    return get_dependencies().db_repo


def get_message_collector() -> MessageCollector:
    """Dependency for message collector."""
    return get_dependencies().message_collector


def get_summary_poster() -> SummaryPoster:
    """Dependency for summary poster."""
    return get_dependencies().summary_poster


def init_dependencies():
    """Initialize dependencies on startup.

    This ensures all components are created and validated before
    the API starts accepting requests.
    """
    deps = get_dependencies()
    # Touch db_repo to ensure database is initialized
    _ = deps.db_repo


def cleanup_dependencies():
    """Clean up dependencies on shutdown."""
    # Currently no cleanup needed, but placeholder for future use
    pass
