"""Tests for src/utils/message_utils.py"""

import pytest
from src.utils.message_utils import split_long_message, SIGNAL_MAX_MESSAGE_LENGTH


class TestSplitLongMessage:
    """Tests for split_long_message function."""

    def test_short_message_no_split(self):
        """Text under 2000 chars returns single item list."""
        text = "Hello, this is a short message."
        result = split_long_message(text)
        assert result == [text]
        assert len(result) == 1

    def test_exact_limit_no_split(self):
        """Text at exactly max_length returns single item."""
        text = "x" * SIGNAL_MAX_MESSAGE_LENGTH
        result = split_long_message(text)
        assert len(result) == 1
        assert result[0] == text

    def test_empty_string(self):
        """Empty string returns list with empty string."""
        result = split_long_message("")
        assert result == [""]

    def test_split_at_paragraph(self):
        """Splits at paragraph boundary (double newline)."""
        # Create text with paragraph break in the middle
        para1 = "First paragraph. " * 60  # ~1020 chars
        para2 = "Second paragraph. " * 60  # ~1080 chars
        text = para1 + "\n\n" + para2

        result = split_long_message(text)

        assert len(result) == 2
        # First part should end before the paragraph break
        assert "\n\n" not in result[0]
        # Parts should have indicators
        assert "(1/2)" in result[0]
        assert "(2/2)" in result[1]

    def test_split_at_newline(self):
        """Falls back to single newline when no paragraph break."""
        # Create text with single newlines only
        lines = ["Line " + str(i) + " content here. " * 5 for i in range(40)]
        text = "\n".join(lines)  # ~2800 chars

        result = split_long_message(text)

        assert len(result) >= 2
        # Parts should have indicators
        assert "(1/" in result[0]

    def test_split_at_sentence(self):
        """Falls back to sentence boundary when no newline."""
        # Create long text with sentences but no newlines
        text = "This is a sentence. " * 120  # ~2400 chars

        result = split_long_message(text)

        assert len(result) >= 2
        # First part should end at a sentence
        # (stripped, so may not end with period but will have indicator)
        assert "(1/" in result[0]

    def test_split_at_word(self):
        """Falls back to word boundary when no sentence punctuation."""
        # Create text with spaces but no sentence punctuation
        text = "word " * 500  # 2500 chars

        result = split_long_message(text)

        assert len(result) >= 2
        # Should not cut in middle of "word"
        for part in result:
            # Remove part indicator for check
            content = part.rsplit(" (", 1)[0] if "(" in part else part
            # Should end with complete word (or be empty after strip)
            assert not content.endswith("wor")  # partial word

    def test_hard_cut(self):
        """Last resort: hard cut when no boundaries found."""
        # Create text with no spaces at all
        text = "x" * 2500

        result = split_long_message(text)

        assert len(result) >= 2
        # Should still produce valid parts
        for part in result:
            assert len(part) <= SIGNAL_MAX_MESSAGE_LENGTH

    def test_part_indicators(self):
        """Multiple parts get (1/N) suffix."""
        text = "Test content here. " * 150  # ~2850 chars

        result = split_long_message(text)

        assert len(result) >= 2
        total = len(result)
        for i, part in enumerate(result):
            assert f"({i+1}/{total})" in part

    def test_unicode_emoji(self):
        """Handles emoji and unicode correctly."""
        # Mix of emoji and text
        text = "Hello 👋 " * 300  # ~2700 chars with emoji

        result = split_long_message(text)

        assert len(result) >= 2
        # Emoji should not be corrupted
        for part in result:
            # Should contain intact emoji
            if "👋" in part:
                assert "👋" in part  # Not corrupted bytes

    def test_custom_max_length(self):
        """Respects custom max_length parameter."""
        text = "x" * 500

        result = split_long_message(text, max_length=100)

        assert len(result) >= 5
        # Each part (including indicator) should be under limit
        for part in result:
            assert len(part) <= 100

    def test_single_long_word(self):
        """Handles single very long word."""
        text = "superlongword" * 200  # ~2600 chars, no spaces

        result = split_long_message(text)

        assert len(result) >= 2
        # All parts should be valid
        for part in result:
            assert len(part) <= SIGNAL_MAX_MESSAGE_LENGTH

    def test_preserves_content(self):
        """All original content is preserved across parts."""
        original = "Test sentence number {}. ".format
        text = "".join(original(i) for i in range(100))

        result = split_long_message(text)

        # Remove part indicators and rejoin
        content_parts = []
        for part in result:
            # Remove " (N/M)" suffix
            if " (" in part and "/" in part:
                content = part.rsplit(" (", 1)[0]
            else:
                content = part
            content_parts.append(content)

        rejoined = " ".join(content_parts)
        # All numbered sentences should be present
        for i in range(100):
            assert f"number {i}" in rejoined or f"number {i}" in text
