"""Signal-CLI wrapper for interacting with Signal messenger."""

import json
import subprocess
import logging
import urllib.parse
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class SignalCLIException(Exception):
    """Exception raised for Signal-CLI errors."""
    pass


class SignalCLI:
    """Wrapper for signal-cli command line interface."""

    def __init__(self, phone_number: str, config_dir: str = "/signal-cli-config"):
        """Initialize Signal-CLI wrapper.

        Args:
            phone_number: The registered phone number (e.g., +1234567890)
            config_dir: Directory for signal-cli configuration
        """
        self.phone_number = phone_number
        self.config_dir = config_dir
        self.cli_path = "signal-cli"

    def _run_command(self, args: List[str], check_output: bool = True, use_account: bool = True, json_output: bool = False) -> Optional[str]:
        """Run a signal-cli command.

        Args:
            args: Command arguments
            check_output: Whether to capture and return output
            use_account: Whether to include the account (-a) flag
            json_output: Whether to request JSON output format

        Returns:
            Command output if check_output=True, None otherwise

        Raises:
            SignalCLIException: If command fails
        """
        cmd = [
            self.cli_path,
            "--config", self.config_dir,
        ]

        # Only add account flag if needed (not for linking)
        if use_account:
            cmd.extend(["-a", self.phone_number])

        # Add JSON output flag if requested (must come before subcommand)
        if json_output:
            cmd.extend(["-o", "json"])

        cmd.extend(args)

        logger.debug(f"Running command: {' '.join(cmd)}")

        try:
            if check_output:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True
                )
                return result.stdout
            else:
                subprocess.run(cmd, check=True)
                return None
        except subprocess.CalledProcessError as e:
            error_msg = f"Signal-CLI command failed: {e.stderr if e.stderr else str(e)}"
            logger.error(error_msg)
            raise SignalCLIException(error_msg)

    def is_registered(self) -> bool:
        """Check if the phone number is already registered."""
        try:
            # Try to get account info
            self._run_command(["listIdentities"])
            return True
        except SignalCLIException:
            return False

    def register(self, use_voice: bool = False, captcha: str = None) -> str:
        """Register a new phone number with Signal.

        Args:
            use_voice: Use voice call instead of SMS for verification
            captcha: Optional CAPTCHA token from signalcaptchas.org

        Returns:
            Registration message

        Raises:
            SignalCLIException: If registration fails
        """
        args = ["register"]
        if use_voice:
            args.append("--voice")
        if captcha:
            args.extend(["--captcha", captcha])

        output = self._run_command(args)
        logger.info(f"Registration initiated for {self.phone_number}")
        return output

    def verify(self, verification_code: str) -> str:
        """Verify a phone number with the code received via SMS/voice.

        Args:
            verification_code: 6-digit verification code

        Returns:
            Verification result message

        Raises:
            SignalCLIException: If verification fails
        """
        output = self._run_command(["verify", verification_code])
        logger.info(f"Phone number {self.phone_number} verified successfully")
        return output

    def receive_messages(self, timeout: int = 5) -> List[Dict[str, Any]]:
        """Receive messages from Signal.

        Args:
            timeout: Timeout in seconds for receiving messages

        Returns:
            List of message dictionaries

        Raises:
            SignalCLIException: If receive fails
        """
        try:
            output = self._run_command([
                "receive",
                "--timeout", str(timeout),
                "--trust-new-identities", "always"  # Auto-accept message requests (for bot accounts)
            ], json_output=True)

            if not output or output.strip() == "":
                return []

            # Parse JSON lines
            messages = []
            for line in output.strip().split("\n"):
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON line: {line[:100]}")
                        continue

            return messages

        except SignalCLIException as e:
            # Timeout is not really an error
            if "timeout" in str(e).lower():
                return []
            raise

    def list_groups(self) -> List[Dict[str, Any]]:
        """List all groups the account is a member of.

        Returns:
            List of group dictionaries with id, name, members, and description
        """
        output = self._run_command(["listGroups", "-d"])

        logger.debug(f"Raw listGroups output:\n{output}")

        groups = []
        if output:
            # Parse the output - signal-cli outputs all group fields on one long line
            # Format: "Id: xxx Name: xxx Description: xxx Active: xxx Blocked: xxx Members: [...]"
            # BUT: Descriptions can contain newlines, so we need to reconstruct multi-line entries
            import re

            # First pass: Reconstruct multi-line entries
            # Lines not starting with "Id:" are continuations of the previous line
            raw_lines = output.split("\n")
            reconstructed_lines = []
            current_line = ""

            for raw_line in raw_lines:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                if raw_line.startswith("Id:"):
                    # Start of new group entry
                    if current_line:
                        reconstructed_lines.append(current_line)
                    current_line = raw_line
                else:
                    # Continuation of previous line (multi-line Description)
                    current_line += " " + raw_line

            # Don't forget the last group
            if current_line:
                reconstructed_lines.append(current_line)

            # Second pass: Parse each complete group entry
            for line in reconstructed_lines:
                current_group = {}

                # Extract ID
                id_match = re.search(r'Id:\s*([^\s]+)', line)
                if id_match:
                    current_group["id"] = id_match.group(1)
                    logger.debug(f"Found group ID: {current_group['id']}")

                # Extract Name (everything between "Name: " and " Description:")
                name_match = re.search(r'Name:\s+(.+?)\s+Description:', line)
                if name_match:
                    current_group["name"] = name_match.group(1).strip()
                    logger.debug(f"Found group name: {current_group['name']}")

                # Extract Description (everything between "Description: " and " Active:")
                desc_match = re.search(r'Description:\s+(.+?)\s+Active:', line)
                if desc_match:
                    desc_text = desc_match.group(1).strip()
                    if desc_text:  # Only add if not empty
                        current_group["description"] = desc_text

                # Extract Members (everything after "Members: ")
                # Format: Members: [uuid-1, uuid-2, +phone-number, ...]
                members_match = re.search(r'Members:\s*\[(.*?)\]\s*Pending', line)
                if members_match:
                    members_str = members_match.group(1)
                    members = []

                    # Split by comma and process each member
                    member_items = [item.strip() for item in members_str.split(',')]
                    for item in member_items:
                        if not item:
                            continue

                        member = {}
                        # Check if it's a phone number (starts with +)
                        if item.startswith('+'):
                            member["phone_number"] = item
                        else:
                            # It's a UUID
                            member["uuid"] = item

                        members.append(member)

                    current_group["members"] = members
                    logger.debug(f"Found {len(members)} members in group {current_group.get('name')}")

                # Extract Admins (format: Admins: [uuid-1, uuid-2, +phone-number, ...])
                admins_match = re.search(r'Admins:\s*\[(.*?)\]', line)
                if admins_match:
                    admins_str = admins_match.group(1)
                    admins = []

                    # Split by comma and process each admin
                    admin_items = [item.strip() for item in admins_str.split(',')]
                    for item in admin_items:
                        if not item:
                            continue

                        admin = {}
                        # Check if it's a phone number (starts with +)
                        if item.startswith('+'):
                            admin["phone_number"] = item
                        else:
                            # It's a UUID
                            admin["uuid"] = item

                        admins.append(admin)

                    current_group["admins"] = admins
                    logger.debug(f"Found {len(admins)} admins in group {current_group.get('name')}")

                if current_group.get("id"):
                    logger.debug(f"Parsed group: {current_group}")
                    groups.append(current_group)

        logger.info(f"Parsed {len(groups)} groups from signal-cli")
        return groups

    def get_group_info(self, group_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a specific group.

        Args:
            group_id: The Signal group ID

        Returns:
            Group information dictionary or None if not found
        """
        groups = self.list_groups()
        for group in groups:
            if group.get("id") == group_id:
                return group
        return None

    def list_contacts(self) -> List[Dict[str, Any]]:
        """List all known contacts with profile names.

        Returns:
            List of contact dictionaries with uuid, phone_number, and name
        """
        output = self._run_command(["listContacts"])

        logger.debug(f"Raw listContacts output (first 500 chars):\n{output[:500]}")

        contacts = []
        if output:
            import re

            for line in output.strip().split("\n"):
                if not line.strip():
                    continue

                contact = {}

                # Extract phone number (may be empty)
                phone_match = re.search(r'Number:\s*([+\d]+)', line)
                if phone_match:
                    contact["phone_number"] = phone_match.group(1)

                # Extract ACI (UUID) - this is the primary identifier
                aci_match = re.search(r'ACI:\s*([a-f0-9\-]+)', line)
                if aci_match:
                    contact["uuid"] = aci_match.group(1)

                # Extract Profile name (display name in Signal)
                profile_name_match = re.search(r'Profile name:\s*([^\s].*?)\s+(?:Username:|Color:|Blocked:|$)', line)
                if profile_name_match:
                    profile_name = profile_name_match.group(1).strip()
                    if profile_name:  # Only add if not empty
                        contact["name"] = profile_name

                # Only add if we have a UUID (primary identifier)
                if contact.get("uuid"):
                    contacts.append(contact)
                    logger.debug(f"Parsed contact: {contact.get('name', 'No name')} ({contact.get('uuid')[:12]}...)")

        logger.info(f"Parsed {len(contacts)} contacts from signal-cli")
        return contacts

    def get_cached_recipients(self) -> List[Dict[str, Any]]:
        """Read signal-cli's recipient cache database for profile information.

        This accesses signal-cli's internal SQLite database which contains cached
        profile information for all known recipients (not just contacts).

        Returns:
            List of recipient dictionaries with uuid, phone_number, and name
        """
        import sqlite3
        import os

        recipients = []

        # Find the account database
        # Format: {config_dir}/data/{phone_sanitized}.d/account.db
        data_dir = os.path.join(self.config_dir, "data")
        if not os.path.exists(data_dir):
            logger.warning(f"Signal-CLI data directory not found: {data_dir}")
            return recipients

        # Find the account directory (ends with .d)
        account_dirs = [d for d in os.listdir(data_dir) if d.endswith('.d')]
        if not account_dirs:
            logger.warning(f"No account directories found in {data_dir}")
            return recipients

        # Use the first account directory
        account_dir = os.path.join(data_dir, account_dirs[0])
        db_path = os.path.join(account_dir, "account.db")

        if not os.path.exists(db_path):
            logger.warning(f"Account database not found: {db_path}")
            return recipients

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Query recipients with profile information
            query = """
                SELECT aci, number, profile_given_name, profile_family_name
                FROM recipient
                WHERE aci IS NOT NULL
            """
            cursor.execute(query)

            for row in cursor.fetchall():
                aci, number, given_name, family_name = row

                recipient = {"uuid": aci}

                if number:
                    recipient["phone_number"] = number

                # Combine given and family names
                name_parts = []
                if given_name:
                    name_parts.append(given_name)
                if family_name:
                    name_parts.append(family_name)

                if name_parts:
                    recipient["name"] = " ".join(name_parts)
                    logger.debug(f"Found cached recipient: {recipient['name']} ({aci[:12]}...)")

                recipients.append(recipient)

            conn.close()
            logger.info(f"Loaded {len(recipients)} recipients from signal-cli cache")

            # Count how many have names
            with_names = sum(1 for r in recipients if "name" in r)
            logger.info(f"  {with_names} recipients have profile names")

        except Exception as e:
            logger.error(f"Error reading signal-cli recipient database: {e}")
            return []

        return recipients

    def send_message(self, recipient: str, message: str, group_id: str = None):
        """Send a message (primarily for testing).

        Args:
            recipient: Phone number or group ID
            message: Message text
            group_id: Group ID if sending to group
        """
        args = ["send", "-m", message]

        if group_id:
            args.extend(["-g", group_id])
        else:
            args.append(recipient)

        self._run_command(args, check_output=False)
        logger.info(f"Message sent to {group_id or recipient}")

    def link_device(self, device_name: str = "privacy-summarizer") -> str:
        """Link signal-cli as a secondary device to an existing Signal account.

        Args:
            device_name: Name for this linked device

        Returns:
            The linking URI (sgnl://linkdevice?...) to be encoded as QR code

        Raises:
            SignalCLIException: If linking fails to generate URI
        """
        args = ["link", "-n", device_name]

        # Build command manually because link has special behavior
        cmd = [
            self.cli_path,
            "--config", self.config_dir,
        ] + args

        logger.debug(f"Running link command: {' '.join(cmd)}")

        try:
            # Run the command, capture output even if it fails
            # (link command times out waiting for QR scan, which is expected)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False  # Don't raise exception on non-zero exit
            )

            # Combine stdout and stderr to search for URI
            output = result.stdout + result.stderr

            # The output contains the linking URI
            # Format: sgnl://linkdevice?uuid=...&pub_key=...
            for line in output.split("\n"):
                if line.strip().startswith("sgnl://linkdevice"):
                    linking_uri = line.strip()
                    # URL-decode the URI (Signal app expects decoded version)
                    linking_uri = urllib.parse.unquote(linking_uri)
                    logger.info(f"Generated linking URI for device: {device_name}")
                    return linking_uri

            # If we didn't find the URI, this is a real error
            logger.error(f"Could not find linking URI in output:\n{output}")
            raise SignalCLIException("Failed to generate linking URI - not found in output")

        except subprocess.SubprocessError as e:
            logger.error(f"Failed to run link command: {e}")
            raise SignalCLIException(f"Failed to execute link command: {e}")
