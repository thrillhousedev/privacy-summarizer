"""Tests for src/signal/cli_wrapper.py"""

import pytest
from unittest.mock import patch, MagicMock
import subprocess
import json

from src.signal.cli_wrapper import SignalCLI, SignalCLIException


class TestSignalCLIInit:
    """Tests for SignalCLI initialization."""

    def test_default_config_dir(self):
        """Uses default config directory."""
        cli = SignalCLI("+15551234567")
        assert cli.phone_number == "+15551234567"
        assert cli.config_dir == "/signal-cli-config"

    def test_custom_config_dir(self):
        """Accepts custom config directory."""
        cli = SignalCLI("+15551234567", config_dir="/custom/path")
        assert cli.config_dir == "/custom/path"


class TestRunCommand:
    """Tests for _run_command method."""

    @patch('subprocess.run')
    def test_basic_command(self, mock_run):
        """Runs command and returns stdout."""
        mock_run.return_value = MagicMock(stdout="output", returncode=0)
        cli = SignalCLI("+15551234567")

        result = cli._run_command(["listGroups"])

        assert result == "output"
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_command_with_account_flag(self, mock_run):
        """Includes account flag by default."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        cli = SignalCLI("+15551234567")

        cli._run_command(["listGroups"])

        cmd = mock_run.call_args[0][0]
        assert "-a" in cmd
        assert "+15551234567" in cmd

    @patch('subprocess.run')
    def test_command_without_account_flag(self, mock_run):
        """Can disable account flag for linking."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        cli = SignalCLI("+15551234567")

        cli._run_command(["link"], use_account=False)

        cmd = mock_run.call_args[0][0]
        assert "-a" not in cmd

    @patch('subprocess.run')
    def test_command_with_json_output(self, mock_run):
        """Adds JSON output flag when requested."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        cli = SignalCLI("+15551234567")

        cli._run_command(["receive"], json_output=True)

        cmd = mock_run.call_args[0][0]
        assert "-o" in cmd
        assert "json" in cmd

    @patch('subprocess.run')
    def test_command_failure_raises_exception(self, mock_run):
        """Raises SignalCLIException on failure."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "signal-cli", stderr="Error message"
        )
        cli = SignalCLI("+15551234567")

        with pytest.raises(SignalCLIException):
            cli._run_command(["badCommand"])


class TestIsRegistered:
    """Tests for is_registered method."""

    @patch('subprocess.run')
    def test_registered(self, mock_run):
        """Returns True when account exists."""
        mock_run.return_value = MagicMock(stdout="identity info", returncode=0)
        cli = SignalCLI("+15551234567")

        assert cli.is_registered() is True

    @patch('subprocess.run')
    def test_not_registered(self, mock_run):
        """Returns False when command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "cmd")
        cli = SignalCLI("+15551234567")

        assert cli.is_registered() is False


class TestReceiveMessages:
    """Tests for receive_messages method."""

    @patch('subprocess.run')
    def test_parses_json_lines(self, mock_run):
        """Parses JSON lines output."""
        messages = [
            {"envelope": {"timestamp": 1234567890}},
            {"envelope": {"timestamp": 1234567891}}
        ]
        output = "\n".join(json.dumps(m) for m in messages)
        mock_run.return_value = MagicMock(stdout=output, returncode=0)

        cli = SignalCLI("+15551234567")
        result = cli.receive_messages(timeout=5)

        assert len(result) == 2
        assert result[0]["envelope"]["timestamp"] == 1234567890

    @patch('subprocess.run')
    def test_empty_output(self, mock_run):
        """Returns empty list for empty output."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        cli = SignalCLI("+15551234567")
        result = cli.receive_messages()

        assert result == []

    @patch('subprocess.run')
    def test_timeout_returns_empty(self, mock_run):
        """Returns empty list on timeout."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr="timeout"
        )

        cli = SignalCLI("+15551234567")
        result = cli.receive_messages()

        assert result == []

    @patch('subprocess.run')
    def test_skips_invalid_json(self, mock_run):
        """Skips lines that aren't valid JSON."""
        output = '{"valid": true}\nNot valid JSON\n{"also": "valid"}'
        mock_run.return_value = MagicMock(stdout=output, returncode=0)

        cli = SignalCLI("+15551234567")
        result = cli.receive_messages()

        assert len(result) == 2


class TestListGroups:
    """Tests for list_groups method."""

    @patch('subprocess.run')
    def test_parses_group_info(self, mock_run):
        """Parses group info from output."""
        output = (
            "Id: abc123 Name: Test Group Description:  Active: true Blocked: false "
            "Members: [uuid-1, uuid-2, +15551234567] Pending members: [] Requesting members: [] Admins: []\n"
        )
        mock_run.return_value = MagicMock(stdout=output, returncode=0)

        cli = SignalCLI("+15551234567")
        result = cli.list_groups()

        assert len(result) == 1
        assert result[0]["id"] == "abc123"
        assert result[0]["name"] == "Test Group"
        assert len(result[0]["members"]) == 3

    @patch('subprocess.run')
    def test_multiple_groups(self, mock_run):
        """Parses multiple groups."""
        output = (
            "Id: group1 Name: Group One Description:  Active: true Blocked: false "
            "Members: [uuid-1] Pending members: [] Requesting members: [] Admins: []\n"
            "Id: group2 Name: Group Two Description: A description Active: true Blocked: false "
            "Members: [uuid-2] Pending members: [] Requesting members: [] Admins: []\n"
        )
        mock_run.return_value = MagicMock(stdout=output, returncode=0)

        cli = SignalCLI("+15551234567")
        result = cli.list_groups()

        assert len(result) == 2
        assert result[0]["name"] == "Group One"
        assert result[1]["name"] == "Group Two"
        assert result[1]["description"] == "A description"

    @patch('subprocess.run')
    def test_empty_output(self, mock_run):
        """Returns empty list for no groups."""
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        cli = SignalCLI("+15551234567")
        result = cli.list_groups()

        assert result == []

    @patch('subprocess.run')
    def test_parses_admins(self, mock_run):
        """Parses admin list from group output."""
        output = (
            "Id: abc123 Name: Test Group Description:  Active: true Blocked: false "
            "Members: [uuid-1, uuid-2] Pending members: [] Requesting members: [] Admins: [uuid-1]\n"
        )
        mock_run.return_value = MagicMock(stdout=output, returncode=0)

        cli = SignalCLI("+15551234567")
        result = cli.list_groups()

        assert len(result) == 1
        assert "admins" in result[0]
        assert len(result[0]["admins"]) == 1
        assert result[0]["admins"][0]["uuid"] == "uuid-1"

    @patch('subprocess.run')
    def test_parses_multiple_admins(self, mock_run):
        """Parses multiple admins including phone numbers."""
        output = (
            "Id: abc123 Name: Test Group Description:  Active: true Blocked: false "
            "Members: [uuid-1, uuid-2, +15551234567] Pending members: [] Requesting members: [] "
            "Admins: [uuid-1, +15551234567]\n"
        )
        mock_run.return_value = MagicMock(stdout=output, returncode=0)

        cli = SignalCLI("+15551234567")
        result = cli.list_groups()

        assert len(result[0]["admins"]) == 2
        assert result[0]["admins"][0]["uuid"] == "uuid-1"
        assert result[0]["admins"][1]["phone_number"] == "+15551234567"

    @patch('subprocess.run')
    def test_empty_admins_list(self, mock_run):
        """Handles empty admin list."""
        output = (
            "Id: abc123 Name: Test Group Description:  Active: true Blocked: false "
            "Members: [uuid-1] Pending members: [] Requesting members: [] Admins: []\n"
        )
        mock_run.return_value = MagicMock(stdout=output, returncode=0)

        cli = SignalCLI("+15551234567")
        result = cli.list_groups()

        assert "admins" in result[0]
        assert result[0]["admins"] == []


class TestSendMessage:
    """Tests for send_message method."""

    @patch('subprocess.run')
    def test_send_to_group(self, mock_run):
        """Sends message to group using -g flag."""
        mock_run.return_value = MagicMock(returncode=0)
        cli = SignalCLI("+15551234567")

        cli.send_message(recipient="ignored", message="Hello", group_id="group-abc")

        cmd = mock_run.call_args[0][0]
        assert "-g" in cmd
        assert "group-abc" in cmd
        assert "-m" in cmd
        assert "Hello" in cmd

    @patch('subprocess.run')
    def test_send_to_recipient(self, mock_run):
        """Sends message to recipient."""
        mock_run.return_value = MagicMock(returncode=0)
        cli = SignalCLI("+15551234567")

        cli.send_message(recipient="+15559876543", message="Hi there")

        cmd = mock_run.call_args[0][0]
        assert "+15559876543" in cmd
        assert "-g" not in cmd


class TestLinkDevice:
    """Tests for link_device method."""

    @patch('subprocess.run')
    def test_extracts_linking_uri(self, mock_run):
        """Extracts sgnl:// URI from output."""
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="sgnl://linkdevice?uuid=abc&pub_key=xyz",
            returncode=0
        )
        cli = SignalCLI("+15551234567")

        result = cli.link_device("test-device")

        assert result.startswith("sgnl://linkdevice")
        assert "uuid=abc" in result

    @patch('subprocess.run')
    def test_uri_in_stdout(self, mock_run):
        """Handles URI in stdout."""
        mock_run.return_value = MagicMock(
            stdout="sgnl://linkdevice?uuid=abc123&pub_key=xyz789",
            stderr="",
            returncode=0
        )
        cli = SignalCLI("+15551234567")

        result = cli.link_device()

        assert "uuid=abc123" in result

    @patch('subprocess.run')
    def test_no_uri_raises_exception(self, mock_run):
        """Raises exception if no URI found."""
        mock_run.return_value = MagicMock(stdout="No URI", stderr="", returncode=0)
        cli = SignalCLI("+15551234567")

        with pytest.raises(SignalCLIException, match="linking URI"):
            cli.link_device()
