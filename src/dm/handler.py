"""DM Handler for conversational AI chat via Signal."""

import logging
import os
from typing import Optional

from ..ai.ollama_client import OllamaClient
from ..database.repository import DatabaseRepository
from ..utils.message_utils import split_long_message

logger = logging.getLogger(__name__)


class DMHandler:
    """Handles direct messages with conversational AI.

    Provides ChatGPT-like conversation experience via Signal DMs.
    Messages are stored temporarily (default 48hr retention) and support:
    - Conversational chat with context
    - Text summarization (auto-detected or explicit)
    - Commands: !help, !status, !summary, !!!purge
    """

    COMMANDS = {
        "!help": "Show available commands",
        "!status": "Show bot and AI status",
        "!summary": "Summarize conversation and clear history",
        "!retention": "View/set message retention period",
        "!!!purge": "Delete all conversation history"
    }

    SUMMARIZE_TRIGGERS = [
        "summarize", "summary", "tldr", "tl;dr",
        "sum up", "brief", "condense", "shorten"
    ]

    SYSTEM_PROMPT = """You are a helpful assistant communicating via Signal messenger.
Keep responses concise and conversational.

IMPORTANT RULES:
- Only respond to what the user actually said in their message
- Never fabricate, invent, or roleplay conversations
- Never use markdown headers (like ## or **) in responses
- Keep responses natural and conversational

PRIVACY: When summarizing text, do not repeat names or direct quotes. Use general terms instead."""

    def __init__(
        self,
        ollama: OllamaClient,
        signal_client,
        db_repo: DatabaseRepository,
        enabled: bool = None,
        retention_hours: int = None
    ):
        """Initialize the DM handler.

        Args:
            ollama: Ollama client for AI responses
            signal_client: Signal client for sending messages
            db_repo: Database repository for conversation storage
            enabled: Kill switch (default from env DM_CHAT_ENABLED)
            retention_hours: Retention period (default from env DM_RETENTION_HOURS or 48)
        """
        self.ollama = ollama
        self.signal = signal_client
        self.db = db_repo

        # Kill switch - defaults to True unless explicitly disabled
        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = os.getenv("DM_CHAT_ENABLED", "true").lower() in ("true", "1", "yes")

        # Retention period
        if retention_hours is not None:
            self.retention_hours = retention_hours
        else:
            self.retention_hours = int(os.getenv("DM_RETENTION_HOURS", "48"))

    def handle_dm(self, user_id: str, message: str, timestamp: int = None) -> None:
        """Process an incoming DM.

        Args:
            user_id: Sender's Signal UUID or phone number
            message: Message text
            timestamp: Signal's timestamp_ms (optional)
        """
        if not user_id or not message:
            logger.warning("Received DM with missing user_id or message")
            return

        text = message.strip()
        lower = text.lower()

        logger.info(f"Processing DM from {user_id[:8]}...")

        # Check for commands FIRST (don't store commands, consistent with group chats)
        if lower == "!help":
            self._send_help(user_id)
            return
        if lower == "!status":
            self._send_status(user_id)
            return
        if lower == "!summary":
            self._handle_summary_command(user_id)
            return
        if lower == "!!!purge":
            self._handle_purge_command(user_id)
            return
        if lower.startswith("!retention"):
            self._handle_retention_command(user_id, text)
            return

        # Store non-command user messages
        try:
            self.db.store_dm_message(user_id, "user", text, timestamp)
        except Exception as e:
            logger.error(f"Failed to store DM message: {e}")
            # Continue anyway - we can still respond

        # Kill switch check (after storing message)
        if not self.enabled:
            self._send_disabled_message(user_id)
            return

        # Ollama availability check (after storing message)
        if not self.ollama.is_available():
            self._send_ollama_offline(user_id)
            return

        # Process as chat or summarization
        try:
            intent = self._detect_intent(text)

            if intent == "summarize_conversation":
                # User wants to summarize their conversation history
                self._handle_summary_command(user_id)
                return  # _handle_summary_command sends its own response
            elif intent == "summarize_text":
                response = self._handle_summarize_request(text)
            else:
                response = self._handle_chat(user_id, text)

            # Store and send response
            self.db.store_dm_message(user_id, "assistant", response)
            self._send_message(user_id, response)

        except Exception as e:
            logger.error(f"Error processing DM: {e}", exc_info=True)
            self._send_message(
                user_id,
                "Sorry, I encountered an error processing your message. Please try again."
            )

    def _detect_intent(self, message: str) -> str:
        """Auto-detect if user wants summarization or chat.

        Args:
            message: User's message text

        Returns:
            "summarize_conversation", "summarize_text", or "chat"
        """
        lower = message.lower()

        # Check if user wants to summarize their conversation history
        conversation_phrases = [
            "summarize the conversation", "summarize our conversation",
            "summarize this conversation", "summary of conversation",
            "summarize my conversation", "summarize chat", "summarize our chat",
            "tldr conversation", "tldr chat"
        ]
        for phrase in conversation_phrases:
            if phrase in lower:
                return "summarize_conversation"

        # Long text with line breaks likely wants text summarization
        if len(message) > 1000 and "\n" in message:
            return "summarize_text"

        # Explicit summarization trigger with substantial content
        for trigger in self.SUMMARIZE_TRIGGERS:
            if trigger in lower and len(message) > 100:
                return "summarize_text"

        # Default to chat
        return "chat"

    def _handle_chat(self, user_id: str, message: str) -> str:
        """Handle conversational chat with history context.

        Args:
            user_id: User's Signal UUID or phone number
            message: Current message

        Returns:
            AI response text
        """
        # Get all history (Ollama handles truncation via max_input_tokens)
        history = self.db.get_dm_history(user_id)

        # Build messages for Ollama chat
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]

        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})

        # Generate response
        return self.ollama.chat(messages, temperature=0.7)

    def _handle_summarize_request(self, text: str) -> str:
        """Handle a summarization request.

        Args:
            text: Text containing summarization request and content

        Returns:
            Summary text
        """
        # Try to extract the text to summarize
        # Remove common request phrases
        content = text
        for trigger in self.SUMMARIZE_TRIGGERS:
            content = content.lower().replace(trigger, "").replace(trigger.upper(), "")

        # Remove common prefixes
        for prefix in ["this:", "this", "the following:", "the following", "please", "can you", "could you"]:
            if content.lower().strip().startswith(prefix):
                content = content[len(prefix):].strip()

        # If there's substantial content to summarize
        if len(content.strip()) > 50:
            # Use privacy-focused prompt
            prompt = f"""Summarize the following text concisely.

PRIVACY REQUIREMENTS:
- DO NOT include any names, usernames, or identifying information
- DO NOT include direct quotes
- Use general terms like "someone", "a person", "participants"
- Focus on key points and themes only

Text:
{content.strip()}

Summary:"""
            return self.ollama.generate(prompt=prompt, temperature=0.3)
        else:
            # Not enough content - treat as chat
            return self.ollama.generate(
                prompt=text,
                system_prompt=self.SYSTEM_PROMPT,
                temperature=0.7
            )

    def _handle_summary_command(self, user_id: str) -> None:
        """Handle !summary command - summarize and purge conversation.

        Args:
            user_id: User's Signal UUID or phone number
        """
        # Check if Ollama is available for summary
        if not self.ollama.is_available():
            self._send_message(
                user_id,
                "Cannot generate summary - AI service is currently offline. "
                "Use !!!purge if you just want to clear history."
            )
            return

        history = self.db.get_dm_history(user_id)

        # Filter out command messages for summary
        content_messages = [
            msg for msg in history
            if not msg.content.startswith("!")
        ]

        if len(content_messages) < 2:
            self._send_message(user_id, "No conversation to summarize.")
            return

        # Build text for summarization
        text = "\n".join([
            f"{msg.role}: {msg.content}"
            for msg in content_messages
        ])

        try:
            # Use privacy-focused prompt
            prompt = f"""Summarize this conversation concisely.

PRIVACY REQUIREMENTS:
- DO NOT include any names, usernames, or identifying information
- DO NOT include direct quotes
- Use general terms like "someone", "a person", "participants"
- Focus on key points and themes only

Conversation:
{text}

Summary:"""
            summary = self.ollama.generate(prompt=prompt, temperature=0.3)

            # Purge conversation
            count = self.db.purge_dm_messages(user_id)

            self._send_message(
                user_id,
                f"📊 Conversation Summary\n\n"
                f"💬 Messages: {len(content_messages)}\n\n"
                f"📝 Summary:\n{summary}\n\n"
                f"✅ {count} messages cleared."
            )
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            self._send_message(
                user_id,
                "Failed to generate summary. Please try again."
            )

    def _handle_purge_command(self, user_id: str) -> None:
        """Handle !!!purge command - delete all conversation history.

        Args:
            user_id: User's Signal UUID or phone number
        """
        count = self.db.purge_dm_messages(user_id)
        self._send_message(user_id, f"Deleted {count} messages from conversation history.")

    def _handle_retention_command(self, user_id: str, text: str) -> None:
        """Handle !retention [hours] command - view or set retention period.

        Args:
            user_id: User's Signal UUID or phone number
            text: Full command text (e.g., "!retention" or "!retention 24")
        """
        parts = text.strip().split()

        if len(parts) == 1:
            # Just "!retention" - show current setting
            hours = self.db.get_dm_retention_hours(user_id)
            self._send_message(
                user_id,
                f"Your DM retention period is {hours} hours.\n"
                f"Messages older than this are automatically deleted.\n\n"
                f"Use !retention [hours] to change (1-168)."
            )
            return

        # Parse hours argument
        try:
            hours = int(parts[1])
            if not 1 <= hours <= 168:
                raise ValueError("Out of range")
        except (ValueError, IndexError):
            self._send_message(
                user_id,
                "Invalid retention period. Must be between 1 and 168 hours (7 days)."
            )
            return

        # Set the new retention period
        self.db.set_dm_retention_hours(user_id, hours)
        self._send_message(user_id, f"Retention period set to {hours} hours.")

    def _send_help(self, user_id: str) -> None:
        """Send help message with available commands.

        Args:
            user_id: User's Signal UUID or phone number
        """
        help_text = """📖 DM Commands

📋 !help - Show this help
📊 !status - Show bot status
📝 !summary - Summarize and clear history
⏰ !retention - View your retention period
⏰ !retention [hours] - Set retention (1-168h)
🗑️ !!!purge - Delete all conversation history

💬 Chat normally or paste text to summarize!
📖 Docs: https://next.maidan.cloud/apps/collectives/p/SCXCe4p3RDexBZC/Privacy-Summarizer-Docs-4"""

        self._send_message(user_id, help_text)

    def _send_status(self, user_id: str) -> None:
        """Send status message with current state.

        Args:
            user_id: User's Signal UUID or phone number
        """
        # Check Ollama status
        service_status = "Online" if self.ollama.is_available() else "Offline"
        status_emoji = "✅" if self.ollama.is_available() else "❌"

        # Get message count for this user
        message_count = self.db.get_dm_message_count(user_id)

        # Get per-user retention (or default)
        retention_hours = self.db.get_dm_retention_hours(user_id)

        status_text = f"""📊 Status

{status_emoji} Service: {service_status}
💬 Messages: {message_count} stored
⏰ Retention: {retention_hours} hours

Use !retention [hours] to change (1-168)."""

        self._send_message(user_id, status_text)

    def _send_disabled_message(self, user_id: str) -> None:
        """Send message when DM feature is disabled.

        Args:
            user_id: User's Signal UUID or phone number
        """
        self._send_message(
            user_id,
            "Message received! DM conversations are paused right now, "
            "but I've saved your message. I'll be able to respond when "
            "the service is back online.\n\n"
            "Commands still work: !help, !status, !summary, !!!purge"
        )

    def _send_ollama_offline(self, user_id: str) -> None:
        """Send message when Ollama is offline.

        Args:
            user_id: User's Signal UUID or phone number
        """
        self._send_message(
            user_id,
            "Message received! The AI service is temporarily offline, "
            "but I've saved your message. I'll be able to respond when "
            "it's back up.\n\n"
            "Commands still work: !help, !status, !summary, !!!purge"
        )

    def _send_message(self, user_id: str, message: str) -> None:
        """Send a message to a user, splitting if necessary.

        Args:
            user_id: Recipient's Signal UUID or phone number
            message: Message text
        """
        # Split long messages for Signal's limit
        parts = split_long_message(message)

        for part in parts:
            try:
                self.signal.send_message(recipient=user_id, message=part)
            except Exception as e:
                logger.error(f"Failed to send DM to {user_id[:8]}...: {e}")

    def set_enabled(self, enabled: bool) -> None:
        """Set the enabled state (kill switch).

        Args:
            enabled: Whether DM chat is enabled
        """
        self.enabled = enabled
        logger.info(f"DM chat {'enabled' if enabled else 'disabled'}")
