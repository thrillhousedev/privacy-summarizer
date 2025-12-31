"""Tests for src/utils/timezone.py"""

import os
import pytest
from datetime import datetime
from unittest.mock import patch
import pytz

# Import after setting up mocks to avoid cached timezone
import src.utils.timezone as tz_module


class TestGetConfiguredTimezone:
    """Tests for get_configured_timezone function."""

    def setup_method(self):
        """Reset the cached timezone before each test."""
        tz_module._configured_timezone = None

    def test_valid_timezone(self):
        """Parses valid IANA timezone string."""
        with patch.dict(os.environ, {'TIMEZONE': 'America/Chicago'}):
            tz_module._configured_timezone = None
            result = tz_module.get_configured_timezone()
            assert result == pytz.timezone('America/Chicago')

    def test_invalid_timezone_fallback(self):
        """Invalid timezone string falls back to UTC."""
        with patch.dict(os.environ, {'TIMEZONE': 'Invalid/Timezone'}):
            tz_module._configured_timezone = None
            result = tz_module.get_configured_timezone()
            assert result == pytz.UTC

    def test_missing_env_var(self):
        """Missing TIMEZONE env var defaults to UTC."""
        env = os.environ.copy()
        env.pop('TIMEZONE', None)
        with patch.dict(os.environ, env, clear=True):
            tz_module._configured_timezone = None
            result = tz_module.get_configured_timezone()
            assert result == pytz.UTC

    def test_caching(self):
        """Second call returns cached value."""
        with patch.dict(os.environ, {'TIMEZONE': 'Europe/London'}):
            tz_module._configured_timezone = None
            result1 = tz_module.get_configured_timezone()

            # Change env var
            with patch.dict(os.environ, {'TIMEZONE': 'Asia/Tokyo'}):
                result2 = tz_module.get_configured_timezone()

            # Should still be London (cached)
            assert result1 == result2
            assert result2 == pytz.timezone('Europe/London')


class TestNowInTimezone:
    """Tests for now_in_timezone function."""

    def setup_method(self):
        """Reset the cached timezone before each test."""
        tz_module._configured_timezone = None

    def test_returns_aware_datetime(self):
        """Returns timezone-aware datetime."""
        with patch.dict(os.environ, {'TIMEZONE': 'UTC'}):
            tz_module._configured_timezone = None
            result = tz_module.now_in_timezone()
            assert result.tzinfo is not None

    def test_uses_configured_timezone(self):
        """Uses the correct configured timezone."""
        with patch.dict(os.environ, {'TIMEZONE': 'America/New_York'}):
            tz_module._configured_timezone = None
            result = tz_module.now_in_timezone()
            # Check timezone name
            assert 'America/New_York' in str(result.tzinfo) or 'EST' in str(result.tzinfo) or 'EDT' in str(result.tzinfo)


class TestUtcnow:
    """Tests for utcnow function."""

    def test_returns_naive_datetime(self):
        """Returns naive datetime (no tzinfo)."""
        result = tz_module.utcnow()
        assert result.tzinfo is None

    def test_returns_current_time(self):
        """Returns approximately current time."""
        before = datetime.utcnow()
        result = tz_module.utcnow()
        after = datetime.utcnow()

        assert before <= result <= after


class TestToConfiguredTimezone:
    """Tests for to_configured_timezone function."""

    def setup_method(self):
        """Reset the cached timezone before each test."""
        tz_module._configured_timezone = None

    def test_naive_datetime_assumed_utc(self):
        """Naive datetime is assumed to be UTC."""
        with patch.dict(os.environ, {'TIMEZONE': 'America/Chicago'}):
            tz_module._configured_timezone = None

            naive_dt = datetime(2024, 6, 15, 12, 0, 0)  # noon UTC
            result = tz_module.to_configured_timezone(naive_dt)

            # Chicago is UTC-5 or UTC-6, so should be 6 or 7 AM
            assert result.hour in [6, 7]  # Depends on DST
            assert result.tzinfo is not None

    def test_aware_datetime_converted(self):
        """Already-aware datetime is converted correctly."""
        with patch.dict(os.environ, {'TIMEZONE': 'America/Los_Angeles'}):
            tz_module._configured_timezone = None

            # Create UTC-aware datetime
            utc_dt = pytz.UTC.localize(datetime(2024, 6, 15, 20, 0, 0))  # 8 PM UTC
            result = tz_module.to_configured_timezone(utc_dt)

            # LA is UTC-7 in summer, so should be 1 PM
            assert result.hour == 13
            assert result.tzinfo is not None


class TestGetDateInTimezone:
    """Tests for get_date_in_timezone function."""

    def setup_method(self):
        """Reset the cached timezone before each test."""
        tz_module._configured_timezone = None

    def test_returns_midnight(self):
        """Returns datetime at midnight."""
        with patch.dict(os.environ, {'TIMEZONE': 'UTC'}):
            tz_module._configured_timezone = None
            result = tz_module.get_date_in_timezone()

            assert result.hour == 0
            assert result.minute == 0
            assert result.second == 0
            assert result.microsecond == 0

    def test_returns_aware_datetime(self):
        """Returns timezone-aware datetime."""
        with patch.dict(os.environ, {'TIMEZONE': 'Europe/Paris'}):
            tz_module._configured_timezone = None
            result = tz_module.get_date_in_timezone()

            assert result.tzinfo is not None
