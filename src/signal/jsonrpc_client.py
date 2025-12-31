"""JSON-RPC client for signal-cli daemon mode.

This module provides real-time communication with signal-cli running in daemon mode,
enabling instant message handling, auto-accepting group invites, and command processing.
"""

import json
import logging
import os
import threading
import time
from typing import Callable, Dict, Any, List, Optional
from dataclasses import dataclass
import requests

from ..utils.message_utils import split_long_message, SIGNAL_MAX_MESSAGE_LENGTH

logger = logging.getLogger(__name__)


@dataclass
class SignalMessage:
    """Represents a received Signal message."""
    timestamp: int
    source_uuid: str
    source_number: Optional[str]
    group_id: Optional[str]
    group_name: Optional[str]
    message: Optional[str]
    is_group_invite: bool = False
    raw_envelope: Dict[str, Any] = None


class SignalJSONRPCClient:
    """Client for signal-cli JSON-RPC daemon.

    Connects to signal-cli running in daemon mode (--http or --tcp) and provides
    real-time message handling capabilities.
    """

    # Default timeouts (can be overridden via environment variables)
    DEFAULT_HTTP_TIMEOUT = 30  # seconds for HTTP requests
    DEFAULT_RECEIVE_TIMEOUT = 5  # seconds to wait for messages

    def __init__(
        self,
        phone_number: str,
        host: str = "localhost",
        port: int = 7583,
        use_http: bool = True,
        http_timeout: int = None,
        receive_timeout: int = None
    ):
        """Initialize the JSON-RPC client.

        Args:
            phone_number: The registered Signal phone number
            host: Hostname where signal-cli daemon is running
            port: Port number (default 7583 for TCP, 8080 for HTTP)
            use_http: Whether to use HTTP (True) or raw TCP (False)
            http_timeout: Timeout for HTTP requests (default 30s, or SIGNAL_HTTP_TIMEOUT env)
            receive_timeout: Timeout for receive calls (default 5s, or SIGNAL_RECEIVE_TIMEOUT env)
        """
        self.phone_number = phone_number
        self.host = host
        self.port = port
        self.use_http = use_http
        self.base_url = f"http://{host}:{port}/api/v1/rpc"

        # Configure timeouts (env vars override defaults, constructor args override env vars)
        self.http_timeout = http_timeout or int(
            os.getenv('SIGNAL_HTTP_TIMEOUT', self.DEFAULT_HTTP_TIMEOUT)
        )
        self.receive_timeout = receive_timeout or int(
            os.getenv('SIGNAL_RECEIVE_TIMEOUT', self.DEFAULT_RECEIVE_TIMEOUT)
        )

        self._message_handlers: List[Callable[[SignalMessage], None]] = []
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None
        self._request_id = 0

    def _next_request_id(self) -> int:
        """Get next request ID for JSON-RPC."""
        self._request_id += 1
        return self._request_id

    def _call_rpc(self, method: str, params: Dict[str, Any] = None) -> Any:
        """Make a JSON-RPC call to signal-cli daemon.

        Args:
            method: RPC method name
            params: Method parameters

        Returns:
            Result from the RPC call

        Raises:
            Exception: If RPC call fails
        """
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "id": self._next_request_id()
        }

        if params:
            payload["params"] = params

        logger.debug(f"RPC call: {method} with params: {params}")

        try:
            response = requests.post(
                self.base_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=self.http_timeout
            )
            response.raise_for_status()

            result = response.json()

            if "error" in result:
                error = result["error"]
                raise Exception(f"RPC error {error.get('code')}: {error.get('message')}")

            return result.get("result")

        except requests.exceptions.RequestException as e:
            logger.error(f"RPC call failed: {e}")
            raise

    def is_daemon_running(self) -> bool:
        """Check if signal-cli daemon is running and accessible."""
        try:
            # Try a simple RPC call
            self._call_rpc("listGroups", {"account": self.phone_number})
            return True
        except Exception as e:
            logger.debug(f"Daemon not accessible: {e}")
            return False

    def list_groups(self) -> List[Dict[str, Any]]:
        """List all groups via RPC."""
        result = self._call_rpc("listGroups", {"account": self.phone_number})
        return result if result else []

    def send_message(self, group_id: str = None, recipient: str = None, message: str = "") -> None:
        """Send a message via RPC.

        Args:
            group_id: Group ID to send to (for group messages)
            recipient: Phone number to send to (for direct messages)
            message: Message text
        """
        params = {
            "account": self.phone_number,
            "message": message
        }

        if group_id:
            params["groupId"] = group_id
        elif recipient:
            params["recipient"] = [recipient]
        else:
            raise ValueError("Must specify either group_id or recipient")

        self._call_rpc("send", params)
        logger.info(f"Message sent to {group_id or recipient}")

    def accept_group_invite(self, group_id: str) -> bool:
        """Accept a pending group invite.

        Args:
            group_id: The group ID to accept invite for

        Returns:
            True if successful, False otherwise
        """
        try:
            # In signal-cli, updateGroup with just the group ID accepts pending invites
            self._call_rpc("updateGroup", {
                "account": self.phone_number,
                "groupId": group_id
            })
            logger.info(f"Accepted group invite for {group_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to accept group invite: {e}")
            return False

    def receive_messages(self) -> List[SignalMessage]:
        """Receive pending messages via RPC.

        Returns:
            List of SignalMessage objects
        """
        try:
            # In single-account daemon mode, receive doesn't need account parameter
            result = self._call_rpc("receive", {
                "timeout": self.receive_timeout
            })

            messages = []
            if result:
                for envelope in result:
                    msg = self._parse_envelope(envelope)
                    if msg:
                        messages.append(msg)
            return messages

        except Exception as e:
            logger.error(f"Failed to receive messages: {e}")
            return []

    def _parse_envelope(self, envelope: Dict[str, Any]) -> Optional[SignalMessage]:
        """Parse a signal-cli envelope into a SignalMessage.

        Args:
            envelope: Raw envelope from signal-cli

        Returns:
            SignalMessage or None if not parseable
        """
        try:
            source_uuid = envelope.get("sourceUuid") or envelope.get("source", {}).get("uuid")
            source_number = envelope.get("sourceNumber") or envelope.get("source", {}).get("number")

            # Check for data message
            data_message = envelope.get("dataMessage")
            sync_message = envelope.get("syncMessage")

            # Get group info
            group_id = None
            group_name = None
            is_group_invite = False

            if data_message:
                group_info = data_message.get("groupInfo") or data_message.get("group")
                if group_info:
                    group_id = group_info.get("groupId")
                    group_name = group_info.get("name")
                    # Check if this is an invite (type = UPDATE with pending members)
                    if group_info.get("type") == "UPDATE":
                        is_group_invite = True

            message_text = None
            if data_message:
                message_text = data_message.get("message")
            elif sync_message and sync_message.get("sentMessage"):
                message_text = sync_message["sentMessage"].get("message")

            return SignalMessage(
                timestamp=envelope.get("timestamp", 0),
                source_uuid=source_uuid,
                source_number=source_number,
                group_id=group_id,
                group_name=group_name,
                message=message_text,
                is_group_invite=is_group_invite,
                raw_envelope=envelope
            )

        except Exception as e:
            logger.warning(f"Failed to parse envelope: {e}")
            return None

    def add_message_handler(self, handler: Callable[[SignalMessage], None]) -> None:
        """Add a handler for incoming messages.

        Args:
            handler: Function that takes a SignalMessage and processes it
        """
        self._message_handlers.append(handler)

    def remove_message_handler(self, handler: Callable[[SignalMessage], None]) -> None:
        """Remove a message handler."""
        if handler in self._message_handlers:
            self._message_handlers.remove(handler)

    def _process_message(self, message: SignalMessage) -> None:
        """Process a message through all registered handlers."""
        for handler in self._message_handlers:
            try:
                handler(message)
            except Exception as e:
                logger.error(f"Message handler error: {e}")


class GroupInviteHandler:
    """Handler that automatically accepts group invites."""

    def __init__(self, client: SignalJSONRPCClient, auto_accept: bool = True):
        """Initialize the handler.

        Args:
            client: SignalJSONRPCClient instance
            auto_accept: Whether to automatically accept all group invites
        """
        self.client = client
        self.auto_accept = auto_accept
        self._pending_groups: Dict[str, str] = {}  # group_id -> group_name

    def handle(self, message: SignalMessage) -> None:
        """Handle incoming messages, auto-accepting group invites if enabled."""
        if message.is_group_invite and message.group_id:
            logger.info(f"Received group invite for: {message.group_name or message.group_id}")

            if self.auto_accept:
                if self.client.accept_group_invite(message.group_id):
                    logger.info(f"Auto-accepted group invite: {message.group_name}")
                    # Send a greeting
                    try:
                        self.client.send_message(
                            group_id=message.group_id,
                            message="Hello! Privacy Summarizer bot is now active and ready to generate summaries."
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send greeting: {e}")
            else:
                self._pending_groups[message.group_id] = message.group_name or "Unknown"
                logger.info(f"Group invite pending manual acceptance: {message.group_id}")

    def get_pending_invites(self) -> Dict[str, str]:
        """Get pending group invites."""
        return self._pending_groups.copy()

    def accept_invite(self, group_id: str) -> bool:
        """Manually accept a pending invite."""
        if self.client.accept_group_invite(group_id):
            if group_id in self._pending_groups:
                del self._pending_groups[group_id]
            return True
        return False


class CommandHandler:
    """Handler for bot commands in group messages and DMs."""

    COMMANDS = {
        "!summary": "Generate summary (default: retention period)",
        "!summary [hours]": "Generate summary for [hours]",
        "!help": "Show available commands",
        "!status": "Show bot status",
        "!!!purge": "Purge all stored messages for this group"
    }

    def __init__(
        self,
        client: SignalJSONRPCClient,
        summarize_callback: Callable[[str, int], str] = None,
        purge_callback: Callable[[str], int] = None,
        get_message_count_callback: Callable[[str], int] = None,
        dm_handler=None
    ):
        """Initialize the command handler.

        Args:
            client: SignalJSONRPCClient instance
            summarize_callback: Function to call for !summary (group_id, hours) -> summary
            purge_callback: Function to call for !!!purge (group_id) -> count of deleted messages
            get_message_count_callback: Function to get message count for a group (group_id) -> count
            dm_handler: Optional DMHandler for processing direct messages
        """
        self.client = client
        self.summarize_callback = summarize_callback
        self.purge_callback = purge_callback
        self.get_message_count_callback = get_message_count_callback
        self.dm_handler = dm_handler

    def handle(self, message: SignalMessage) -> None:
        """Handle incoming messages, processing any commands."""
        if not message.message:
            return

        # Route DMs to DM handler if available
        if not message.group_id:
            if self.dm_handler and message.source_number:
                try:
                    self.dm_handler.handle_dm(
                        message.source_number,
                        message.message,
                        message.timestamp
                    )
                except Exception as e:
                    logger.error(f"Error handling DM: {e}")
            return

        text = message.message.strip().lower()

        if text == "!help":
            self._send_help(message.group_id)
        elif text == "!status":
            self._send_status(message.group_id)
        elif text.startswith("!summary"):
            self._handle_summary(message)
        elif text == "!!!purge":
            self._handle_purge(message)

    def _send_help(self, group_id: str) -> None:
        """Send help message to group."""
        help_text = "Privacy Summarizer Commands:\n\n"
        for cmd, desc in self.COMMANDS.items():
            help_text += f"  {cmd} - {desc}\n"
        help_text += "\nSummaries are privacy-focused: no names or direct quotes."
        help_text += "\n\n📖 Full details: https://next.maidan.cloud/apps/collectives/p/SCXCe4p3RDexBZC/Privacy-Summarizer-Docs-4"

        self.client.send_message(group_id=group_id, message=help_text)

    def _send_status(self, group_id: str) -> None:
        """Send status message to group."""
        message_count = 0
        if self.get_message_count_callback:
            message_count = self.get_message_count_callback(group_id)

        status = f"Privacy Summarizer Status: Active\n\n📬 Messages waiting: {message_count}\n\nUse !summary to generate a summary\nUse !!!purge to delete stored messages"
        self.client.send_message(group_id=group_id, message=status)

    def _handle_summary(self, message: SignalMessage) -> None:
        """Handle summary command."""
        if not self.summarize_callback:
            self.client.send_message(
                group_id=message.group_id,
                message="Summarization not configured. Use scheduled summaries instead."
            )
            return

        # Parse hours from command (e.g., "!summary 24" or "!summary")
        parts = message.message.strip().split()
        hours = 24  # default
        if len(parts) > 1:
            try:
                hours = int(parts[1])
            except ValueError:
                pass

        self.client.send_message(
            group_id=message.group_id,
            message=f"Generating summary for the last {hours} hours..."
        )

        try:
            summary = self.summarize_callback(message.group_id, hours)
            # Split long summaries to fit within Signal's character limit
            summary_parts = split_long_message(summary)
            for part in summary_parts:
                self.client.send_message(group_id=message.group_id, message=part)
                # Small delay between messages to maintain order
                if len(summary_parts) > 1:
                    time.sleep(0.5)
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            self.client.send_message(
                group_id=message.group_id,
                message=f"Failed to generate summary: {str(e)[:100]}"
            )

    def _handle_purge(self, message: SignalMessage) -> None:
        """Handle purge command - delete all stored messages for this group."""
        if not self.purge_callback:
            self.client.send_message(
                group_id=message.group_id,
                message="Purge not configured."
            )
            return

        try:
            count = self.purge_callback(message.group_id)
            self.client.send_message(
                group_id=message.group_id,
                message=f"Purged {count} stored messages for this group."
            )
        except Exception as e:
            logger.error(f"Purge failed: {e}")
            self.client.send_message(
                group_id=message.group_id,
                message=f"Failed to purge messages: {str(e)[:100]}"
            )
