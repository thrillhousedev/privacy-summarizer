"""Timezone utilities for consistent date/time handling across the application."""

import os
import logging
from datetime import datetime
from typing import Optional

import pytz

logger = logging.getLogger(__name__)

# Cache the configured timezone to avoid repeated environment variable lookups
_configured_timezone: Optional[pytz.timezone] = None


def get_configured_timezone() -> pytz.timezone:
    """Get the configured timezone from environment variable.

    Returns:
        pytz timezone object for the configured timezone.
        Defaults to UTC if TIMEZONE env var is not set or invalid.
    """
    global _configured_timezone

    if _configured_timezone is not None:
        return _configured_timezone

    timezone_str = os.getenv('TIMEZONE', 'UTC')

    try:
        _configured_timezone = pytz.timezone(timezone_str)
        logger.debug(f"Using configured timezone: {timezone_str}")
    except pytz.exceptions.UnknownTimeZoneError:
        logger.warning(
            f"Invalid timezone '{timezone_str}' in TIMEZONE environment variable. "
            f"Falling back to UTC. Use IANA timezone strings (e.g., 'America/Chicago')."
        )
        _configured_timezone = pytz.UTC

    return _configured_timezone


def now_in_timezone() -> datetime:
    """Get current datetime in the configured timezone.

    Returns:
        Timezone-aware datetime object in the configured timezone.
    """
    tz = get_configured_timezone()
    return datetime.now(tz)


def utcnow() -> datetime:
    """Get current datetime in UTC.

    This is a wrapper around datetime.utcnow() for consistency and
    to make it easier to refactor to timezone-aware datetimes in the future.

    Returns:
        Naive datetime object in UTC.
    """
    return datetime.utcnow()


def to_configured_timezone(dt: datetime) -> datetime:
    """Convert a datetime to the configured timezone.

    Args:
        dt: Datetime to convert (naive or aware)

    Returns:
        Timezone-aware datetime in the configured timezone.
        If input is naive, assumes it's UTC.
    """
    tz = get_configured_timezone()

    # If naive, assume UTC
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)

    return dt.astimezone(tz)


def get_date_in_timezone() -> datetime:
    """Get the current date (midnight) in the configured timezone.

    Useful for date-based calculations where you want "today" or "yesterday"
    relative to the user's configured timezone, not the system timezone.

    Returns:
        Timezone-aware datetime at midnight in the configured timezone.
    """
    now = now_in_timezone()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)
