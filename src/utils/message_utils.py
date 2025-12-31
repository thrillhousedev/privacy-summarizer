"""Message utilities for Privacy Summarizer.

Shared utilities for message handling across the application.
"""

from typing import List
import ctypes

# Signal has a ~2000 character limit for messages
SIGNAL_MAX_MESSAGE_LENGTH = 2000


def anonymize_group_id(group_id: str) -> str:
    """Generate consistent 4-char hash from group ID for privacy.

    Must match frontend implementation in frontend/src/lib/utils.ts.

    Args:
        group_id: The Signal group ID string

    Returns:
        A 4-character hex hash prefixed with # (e.g., "#A3F2")
    """
    hash_val = 0
    for char in group_id:
        # Replicate JavaScript's (hash << 5) - hash + charCodeAt behavior
        hash_val = ((hash_val << 5) - hash_val) + ord(char)
        # Convert to 32-bit signed integer (like JavaScript's & operation)
        hash_val = ctypes.c_int32(hash_val).value

    # Take absolute value and format as uppercase hex, padded to 4 chars
    return '#' + format(abs(hash_val), 'X')[:4].upper().zfill(4)


def split_long_message(text: str, max_length: int = SIGNAL_MAX_MESSAGE_LENGTH) -> List[str]:
    """Split a long message into multiple parts that fit within Signal's limit.

    Args:
        text: The message text to split
        max_length: Maximum length per message (default: 2000 for Signal)

    Returns:
        List of message parts, each under max_length
    """
    if len(text) <= max_length:
        return [text]

    parts = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            parts.append(remaining)
            break

        # Reserve space for part indicator like " (1/3)"
        effective_max = max_length - 10

        # Try to split at paragraph boundary first
        chunk = remaining[:effective_max]
        split_pos = chunk.rfind('\n\n')

        # If no paragraph break, try single newline
        if split_pos == -1 or split_pos < effective_max // 2:
            split_pos = chunk.rfind('\n')

        # If no newline, try sentence boundary
        if split_pos == -1 or split_pos < effective_max // 2:
            for punct in ['. ', '! ', '? ']:
                pos = chunk.rfind(punct)
                if pos > effective_max // 2:
                    split_pos = pos + 1
                    break

        # If no good boundary, try space
        if split_pos == -1 or split_pos < effective_max // 2:
            split_pos = chunk.rfind(' ')

        # Last resort: hard cut
        if split_pos == -1 or split_pos < effective_max // 2:
            split_pos = effective_max

        parts.append(remaining[:split_pos].rstrip())
        remaining = remaining[split_pos:].lstrip()

    # Add part indicators if we have multiple parts
    if len(parts) > 1:
        total = len(parts)
        parts = [f"{part} ({i+1}/{total})" for i, part in enumerate(parts)]

    return parts
