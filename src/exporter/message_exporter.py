"""Message collector with temporary storage for Privacy Summarizer.

Messages are stored temporarily in the encrypted database until summarized,
then purged according to retention policies.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from ..signal.cli_wrapper import SignalCLI, SignalCLIException
from ..utils.timezone import now_in_timezone
from ..database.repository import DatabaseRepository
from ..database.models import Message

logger = logging.getLogger(__name__)


class MessageCollector:
    """Collect and temporarily store Signal messages for summarization.

    Messages are stored in the encrypted database until:
    1. They are summarized and the summary is posted
    2. They exceed the retention period for their group/schedule

    This solves the message consumption problem where receiving messages
    for one group would lose messages for other groups.
    """

    def __init__(
        self,
        signal_cli: SignalCLI,
        db_repo: DatabaseRepository,
        dm_handler=None
    ):
        """Initialize message collector.

        Args:
            signal_cli: Signal-CLI wrapper instance
            db_repo: Database repository for message storage
            dm_handler: Optional DMHandler for processing direct messages
        """
        self.signal_cli = signal_cli
        self.db_repo = db_repo
        self.dm_handler = dm_handler

    def sync_groups(self) -> int:
        """Sync group metadata only (no members/users stored).

        Returns:
            Number of groups synced
        """
        logger.info("Syncing group metadata from Signal...")
        groups = self.signal_cli.list_groups()

        group_count = 0

        for group in groups:
            group_id = group.get("id")
            name = group.get("name", "Unknown Group")
            description = group.get("description", "")

            if group_id:
                # Sync only group metadata (no member storage)
                self.db_repo.create_group(
                    group_id=group_id,
                    name=name,
                    description=description
                )
                group_count += 1
                logger.debug(f"Synced group: {name} ({group_id})")

        logger.info(f"Synced {group_count} groups")
        return group_count

    def receive_and_store_messages(
        self,
        timeout: int = 30,
        max_attempts: int = None,
        enable_retry: bool = True
    ) -> Tuple[int, int]:
        """Receive messages from Signal and store them in the database.

        All messages from all groups are stored. This solves the problem of
        losing messages when filtering for a specific group.

        Args:
            timeout: Timeout for receiving messages in seconds (per attempt)
            max_attempts: Number of receive attempts (default: from env or 3)
            enable_retry: Enable retry logic with deduplication (default: True)

        Returns:
            Tuple of (total_messages_received, new_messages_stored)
        """
        # Get configuration from environment
        if max_attempts is None:
            max_attempts = int(os.getenv('MESSAGE_COLLECTION_ATTEMPTS', '3'))

        # Legacy single-attempt behavior if retry disabled
        if not enable_retry or max_attempts == 1:
            return self._receive_and_store_single_attempt(timeout)

        # Multi-attempt with deduplication for reliable collection
        logger.info(f"Receiving messages with {max_attempts} attempts (timeout={timeout}s each)")

        total_received = 0
        total_stored = 0
        seen_message_keys = set()

        for attempt in range(1, max_attempts + 1):
            logger.info(f"Collection attempt {attempt}/{max_attempts}...")

            try:
                envelopes = self.signal_cli.receive_messages(timeout=timeout)
                logger.debug(f"Attempt {attempt}: received {len(envelopes)} envelopes")

                attempt_received = 0
                attempt_stored = 0

                for envelope_wrapper in envelopes:
                    try:
                        result = self._process_envelope(envelope_wrapper, seen_message_keys)
                        if result:
                            attempt_received += 1
                            if result.get('is_new'):
                                attempt_stored += 1

                    except Exception as e:
                        logger.error(f"Error processing envelope: {e}")
                        continue

                total_received += attempt_received
                total_stored += attempt_stored

                logger.info(
                    f"Attempt {attempt}: {attempt_received} messages received, "
                    f"{attempt_stored} new stored ({total_stored} total new)"
                )

                # Early exit if no new messages (queue is empty)
                if attempt_received == 0:
                    logger.info(f"No new messages on attempt {attempt}, stopping early")
                    break

            except SignalCLIException as e:
                logger.error(f"Error on attempt {attempt}: {e}")
                continue

        logger.info(f"Message collection complete: {total_received} received, {total_stored} new stored")
        return total_received, total_stored

    def _receive_and_store_single_attempt(self, timeout: int = 30) -> Tuple[int, int]:
        """Single-attempt message collection and storage.

        Args:
            timeout: Timeout for receiving messages in seconds

        Returns:
            Tuple of (total_messages_received, new_messages_stored)
        """
        logger.info("Receiving messages from Signal (single attempt)...")

        try:
            envelopes = self.signal_cli.receive_messages(timeout=timeout)
            logger.info(f"Received {len(envelopes)} envelopes")

            total_received = 0
            total_stored = 0
            seen_keys = set()

            for envelope_wrapper in envelopes:
                try:
                    result = self._process_envelope(envelope_wrapper, seen_keys)
                    if result:
                        total_received += 1
                        if result.get('is_new'):
                            total_stored += 1

                except Exception as e:
                    logger.error(f"Error processing envelope: {e}")
                    continue

            logger.info(f"Collected {total_received} messages, {total_stored} new stored")
            return total_received, total_stored

        except SignalCLIException as e:
            logger.error(f"Error receiving messages: {e}")
            return 0, 0

    def _process_envelope(
        self,
        envelope_wrapper: Dict[str, Any],
        seen_keys: set
    ) -> Optional[Dict[str, Any]]:
        """Process a single envelope and store message/reaction if applicable.

        Args:
            envelope_wrapper: Raw envelope from signal-cli
            seen_keys: Set of already-seen message keys for deduplication

        Returns:
            Dict with 'is_new' key if message was processed, None if skipped
        """
        # Extract the actual envelope from the wrapper
        envelope = envelope_wrapper.get("envelope", {})

        # Check for data message
        data_message = envelope.get("dataMessage")

        # If no dataMessage, check for syncMessage.sentMessage
        if not data_message:
            sync_message = envelope.get("syncMessage")
            if sync_message:
                data_message = sync_message.get("sentMessage")

        if not data_message:
            return None

        # Extract envelope data
        source = envelope.get("source") or envelope.get("sourceNumber")
        source_uuid = envelope.get("sourceUuid")
        timestamp_ms = envelope.get("timestamp", 0)
        sender_id = source_uuid or source

        # Check if this is a group message or DM
        group_info = data_message.get("groupInfo")
        is_dm = group_info is None

        if is_dm:
            # Route DMs to DM handler if available
            if self.dm_handler:
                # Use UUID as primary identifier (works for username-only accounts)
                # Fall back to phone number or source for backwards compatibility
                user_id = source_uuid or envelope.get("sourceNumber") or source
                message_text = data_message.get("message", "")
                if user_id and message_text:
                    try:
                        self.dm_handler.handle_dm(user_id, message_text, timestamp_ms)
                    except Exception as e:
                        logger.error(f"Error handling DM: {e}")
            return None

        # Handle group message only
        group_id = group_info.get("groupId")
        if not group_id:
            return None

        # Ensure group exists in database
        group = self.db_repo.get_group_by_id(group_id)
        if not group:
            self.sync_groups()
            group = self.db_repo.get_group_by_id(group_id)

        if not group:
            logger.warning(f"Could not find group: {group_id}")
            return None

        # Check for reaction
        reaction = data_message.get("reaction")
        if reaction:
            return self._process_reaction(reaction, sender_id, timestamp_ms, group_id, seen_keys)

        # Process regular message
        return self._process_message(data_message, sender_id, timestamp_ms, group_id, seen_keys)

    def _process_message(
        self,
        data_message: Dict[str, Any],
        sender_id: str,
        timestamp_ms: int,
        group_id: str,
        seen_keys: set
    ) -> Optional[Dict[str, Any]]:
        """Process and store a message.

        Args:
            data_message: Data message content from envelope
            sender_id: Sender UUID or phone number
            timestamp_ms: Message timestamp in milliseconds
            group_id: Signal group ID
            seen_keys: Set of seen message keys for deduplication

        Returns:
            Dict with 'is_new' key, or None if skipped
        """
        # Create unique message key for deduplication
        message_key = (timestamp_ms, sender_id, group_id)

        # Skip if we've seen this message before in this session
        if message_key in seen_keys:
            logger.debug(f"Skipping duplicate message: {message_key}")
            return None

        # Mark as seen
        seen_keys.add(message_key)

        # Extract message content
        message_text = data_message.get("message", "")

        # Extract expiresInSeconds for auto-retention setting
        expires_in_seconds = data_message.get("expiresInSeconds", 0)

        # Only auto-update retention if group is set to follow Signal's setting
        settings = self.db_repo.get_group_settings(group_id)
        if settings is None or settings.source == "signal":
            if expires_in_seconds > 0:
                retention_hours = max(1, expires_in_seconds // 3600)
            else:
                retention_hours = 48  # Default when no disappearing messages

            current = self.db_repo.get_group_retention_hours(group_id)
            if retention_hours != current:
                self.db_repo.set_group_retention_hours(group_id, retention_hours, source="signal")
                logger.info(f"Auto-set retention for {group_id[:20]}... to {retention_hours}h from Signal")

        # Store message in database
        message, is_new = self.db_repo.store_message(
            signal_timestamp=timestamp_ms,
            sender_uuid=sender_id,
            group_id=group_id,
            content=message_text
        )

        if is_new:
            logger.debug(f"Stored new message in group {group_id} at {timestamp_ms}")
        else:
            logger.debug(f"Message already exists: {message_key}")

        return {'is_new': is_new, 'message_id': message.id}

    def _process_reaction(
        self,
        reaction: Dict[str, Any],
        reactor_id: str,
        timestamp_ms: int,
        group_id: str,
        seen_keys: set
    ) -> Optional[Dict[str, Any]]:
        """Process and store a reaction.

        Args:
            reaction: Reaction data from envelope
            reactor_id: UUID of person who reacted
            timestamp_ms: Reaction timestamp in milliseconds
            group_id: Signal group ID
            seen_keys: Set of seen reaction keys for deduplication

        Returns:
            Dict with 'is_new' key, or None if skipped
        """
        emoji = reaction.get("emoji")
        target_timestamp = reaction.get("targetSentTimestamp")
        target_author = reaction.get("targetAuthorUuid") or reaction.get("targetAuthor")

        if not emoji or not target_timestamp:
            return None

        # Create unique reaction key for deduplication
        reaction_key = ('reaction', timestamp_ms, reactor_id, group_id)

        if reaction_key in seen_keys:
            return None

        seen_keys.add(reaction_key)

        # Find the target message in our database
        # We need to find by timestamp and group
        messages = self.db_repo.get_messages_for_group(group_id)
        target_message = None
        for msg in messages:
            if msg.signal_timestamp == target_timestamp:
                target_message = msg
                break

        if not target_message:
            logger.debug(f"Reaction target message not found: {target_timestamp}")
            return None

        # Store the reaction
        _, is_new = self.db_repo.store_reaction(
            message_id=target_message.id,
            emoji=emoji,
            reactor_uuid=reactor_id,
            timestamp=timestamp_ms
        )

        if is_new:
            logger.debug(f"Stored reaction {emoji} on message {target_message.id}")

        return {'is_new': is_new}

    # =========================================================================
    # Methods for retrieving stored messages (for summarization)
    # =========================================================================

    def get_messages_for_summary(
        self,
        group_id: str,
        hours: int = 24
    ) -> List[Message]:
        """Get stored messages for a group within a time window.

        Args:
            group_id: Signal group ID
            hours: How many hours back to retrieve

        Returns:
            List of Message objects from the database
        """
        since = datetime.utcnow() - timedelta(hours=hours)
        messages = self.db_repo.get_messages_for_group(group_id, since=since)
        logger.info(f"Retrieved {len(messages)} messages for summary (last {hours} hours)")
        return messages

    def get_messages_since(
        self,
        group_id: str,
        since: datetime
    ) -> List[Message]:
        """Get stored messages for a group since a specific time.

        Args:
            group_id: Signal group ID
            since: Start time (UTC)

        Returns:
            List of Message objects from the database
        """
        messages = self.db_repo.get_messages_for_group(group_id, since=since)
        logger.info(f"Retrieved {len(messages)} messages since {since}")
        return messages

    def get_pending_message_stats(self) -> Dict[str, Any]:
        """Get statistics about pending messages (for UI/monitoring).

        Returns:
            Dict with message counts and timestamps
        """
        return self.db_repo.get_pending_stats()

    def get_reaction_stats(self, group_id: str) -> Dict[str, Any]:
        """Get reaction statistics for a group's messages.

        Args:
            group_id: Signal group ID

        Returns:
            Dict with reaction counts and emoji breakdown
        """
        return self.db_repo.get_reaction_stats_for_group(group_id)

    # =========================================================================
    # Legacy transient methods (for backward compatibility)
    # =========================================================================

    def receive_messages(
        self,
        timeout: int = 30,
        group_filter: str = None,
        max_attempts: int = None,
        enable_retry: bool = True
    ) -> List[Dict[str, Any]]:
        """Receive messages and return them (legacy transient interface).

        DEPRECATED: Use receive_and_store_messages() + get_messages_for_summary()
        for the new store-then-process flow.

        This method still stores messages to DB but also returns them for
        backward compatibility with existing code.

        Args:
            timeout: Timeout for receiving messages in seconds
            group_filter: Optional group ID to filter for specific group
            max_attempts: Number of receive attempts
            enable_retry: Enable retry logic

        Returns:
            List of processed messages with minimal metadata
        """
        logger.warning(
            "receive_messages() is deprecated. "
            "Use receive_and_store_messages() + get_messages_for_summary() instead."
        )

        # Store all messages
        self.receive_and_store_messages(
            timeout=timeout,
            max_attempts=max_attempts,
            enable_retry=enable_retry
        )

        # Return messages from DB (optionally filtered)
        if group_filter:
            messages = self.db_repo.get_messages_for_group(group_filter)
        else:
            # Get all recent messages
            stats = self.db_repo.get_pending_stats()
            messages = []
            for gid in stats.get('messages_by_group', {}).keys():
                messages.extend(self.db_repo.get_messages_for_group(gid))

        # Convert to legacy format
        result = []
        for msg in messages:
            group = self.db_repo.get_group_by_id(msg.group_id)
            result.append({
                "group_id": msg.group_id,
                "group_name": group.name if group else "Unknown",
                "content": msg.content,
                "timestamp": datetime.fromtimestamp(msg.signal_timestamp / 1000),
                "sender_id": msg.sender_uuid
            })

        return result

    def collect_messages_for_group(
        self,
        group_id: str,
        timeout: int = 30
    ) -> List[Dict[str, Any]]:
        """Collect messages for a specific group (legacy interface).

        DEPRECATED: Use receive_and_store_messages() + get_messages_for_summary()

        Args:
            group_id: Signal group ID
            timeout: Timeout in seconds

        Returns:
            List of messages for the specified group
        """
        return self.receive_messages(timeout=timeout, group_filter=group_id)

    def collect_recent_messages_by_time_window(
        self,
        group_id: str,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Collect recent messages within a time window (legacy interface).

        DEPRECATED: Use receive_and_store_messages() + get_messages_for_summary()

        Args:
            group_id: Signal group ID
            hours: How many hours back to consider

        Returns:
            List of recently received messages in legacy format
        """
        logger.warning(
            "collect_recent_messages_by_time_window() is deprecated. "
            "Use receive_and_store_messages() + get_messages_for_summary() instead."
        )

        # First, receive and store any new messages
        self.receive_and_store_messages(timeout=30)

        # Then get from DB with time filter
        messages = self.get_messages_for_summary(group_id, hours=hours)

        # Convert to legacy format
        result = []
        for msg in messages:
            group = self.db_repo.get_group_by_id(msg.group_id)
            msg_time = datetime.fromtimestamp(msg.signal_timestamp / 1000)

            result.append({
                "group_id": msg.group_id,
                "group_name": group.name if group else "Unknown",
                "content": msg.content,
                "timestamp": msg_time,
                "sender_id": msg.sender_uuid
            })

        logger.info(f"Retrieved {len(result)} messages within {hours} hour window")
        return result
