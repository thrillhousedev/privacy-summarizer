"""CLI commands for Signal Summarizer."""

import click
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from ..signal.cli_wrapper import SignalCLI
from ..signal.setup import SetupWizard
from ..database.repository import DatabaseRepository
from ..utils.timezone import now_in_timezone
from ..utils.message_utils import split_long_message
from ..ai.ollama_client import OllamaClient
from ..ai.summarizer import ChatSummarizer
from ..scheduler.jobs import ExportScheduler

logger = logging.getLogger(__name__)


@click.group()
@click.pass_context
def cli(ctx):
    """Privacy Summarizer - Privacy-focused Signal group chat summaries with zero data retention."""
    ctx.ensure_object(dict)


@cli.command()
@click.option('--phone', envvar='SIGNAL_PHONE_NUMBER', required=True, help='Phone number to register')
@click.option('--config-dir', envvar='SIGNAL_CLI_CONFIG_DIR', default='/signal-cli-config', help='Signal-CLI config directory')
@click.option('--voice', is_flag=True, help='Use voice call instead of SMS')
def setup(phone, config_dir, voice):
    """Set up Signal-CLI registration."""
    click.echo("Starting Signal-CLI setup...")

    wizard = SetupWizard(phone, config_dir)
    success = wizard.run_setup(use_voice=voice)

    if success:
        click.echo("\n✓ Setup completed successfully!")
    else:
        click.echo("\n✗ Setup failed. Please try again.")
        exit(1)


@cli.command()
@click.option('--phone', envvar='SIGNAL_PHONE_NUMBER', required=True, help='Phone number')
@click.option('--config-dir', envvar='SIGNAL_CLI_CONFIG_DIR', default='/signal-cli-config', help='Signal-CLI config directory')
def status(phone, config_dir):
    """Check Signal-CLI setup status."""
    wizard = SetupWizard(phone, config_dir)
    wizard.display_status()


@cli.command()
@click.option('--phone', envvar='SIGNAL_PHONE_NUMBER', required=True, help='Phone number')
@click.option('--config-dir', envvar='SIGNAL_CLI_CONFIG_DIR', default='/signal-cli-config', help='Signal-CLI config directory')
@click.option('--name', default='privacy-summarizer', help='Name for this linked device')
def link(phone, config_dir, name):
    """Link signal-cli as a secondary device to your existing Signal account.

    This command generates a linking URI that must be converted to a QR code
    and scanned with your primary Signal device (iPhone/Android).

    Use this instead of 'setup' if you already have Signal on your phone
    and want to add signal-cli as a linked device without replacing your
    primary registration.
    """
    click.echo("\n" + "="*70)
    click.echo("Signal Device Linking")
    click.echo("="*70)
    click.echo(f"\nPhone Number: {phone}")
    click.echo(f"Device Name: {name}\n")

    click.echo("⚠️  IMPORTANT: This will link signal-cli as a SECONDARY device.")
    click.echo("   Your phone will remain your PRIMARY device.")
    click.echo("   Make sure you've removed any old registrations first!\n")

    confirm = input("Continue? (yes/no): ").strip().lower()
    if confirm not in ['yes', 'y']:
        click.echo("\n✗ Linking cancelled.")
        return

    signal_cli = SignalCLI(phone, config_dir)

    try:
        click.echo("\nGenerating linking URI...")
        linking_uri = signal_cli.link_device(name)

        click.echo("\n" + "="*70)
        click.echo("✓ Linking URI Generated!")
        click.echo("="*70)
        click.echo(f"\n{linking_uri}\n")

        click.echo("="*70)
        click.echo("Next Steps:")
        click.echo("="*70)
        click.echo("\n1. GENERATE QR CODE:")
        click.echo("   Option A - Online:")
        click.echo("   • Go to: https://www.qr-code-generator.com/")
        click.echo("   • Select 'URL' type")
        click.echo(f"   • Paste the URI above")
        click.echo("   • Click 'Create QR Code'\n")

        click.echo("   Option B - Command Line (if you have qrencode):")
        click.echo(f"   qrencode -t ansiutf8 '{linking_uri}'\n")

        click.echo("2. SCAN WITH YOUR PHONE:")
        click.echo("   • Open Signal on your iPhone/Android")
        click.echo("   • Tap Settings → Linked Devices")
        click.echo("   • Tap the '+' button")
        click.echo("   • Scan the QR code you generated\n")

        click.echo("3. VERIFY:")
        click.echo("   After scanning, run:")
        click.echo("   docker-compose run --rm privacy-summarizer python -m src.main status\n")

        click.echo("="*70)
        click.echo("⏱️  Note: The linking URI expires after a few minutes!")
        click.echo("   Generate a new one if it expires.")
        click.echo("="*70 + "\n")

    except Exception as e:
        click.echo(f"\n✗ Linking failed: {e}")
        logger.error(f"Linking failed: {e}")
        exit(1)


@cli.command('accept-invite')
@click.option('--phone', envvar='SIGNAL_PHONE_NUMBER', required=True, help='Phone number')
@click.option('--config-dir', envvar='SIGNAL_CLI_CONFIG_DIR', default='/signal-cli-config', help='Signal-CLI config directory')
@click.option('--group-id', help='Group ID to accept invite for (optional, accepts all if not specified)')
@click.option('--list', 'list_only', is_flag=True, help='List pending invites without accepting')
def accept_invite(phone, config_dir, group_id, list_only):
    """Accept pending group invites.

    When added to a Signal group, the bot appears as a "pending member" until
    the invite is accepted. This command accepts those pending invites.

    Without --group-id, it will receive messages and accept all pending invites.
    """
    import subprocess
    import re

    click.echo("\n" + "="*70)
    click.echo("Group Invite Manager")
    click.echo("="*70)

    # First, receive any pending messages to get invites
    click.echo("\nReceiving pending messages...")
    try:
        result = subprocess.run(
            ["signal-cli", "--config", config_dir, "-a", phone, "receive", "--timeout", "5"],
            capture_output=True,
            text=True,
            check=False
        )
    except Exception as e:
        click.echo(f"✗ Failed to receive messages: {e}")

    # List groups to find pending invites
    click.echo("Checking for pending group invites...\n")
    try:
        result = subprocess.run(
            ["signal-cli", "--config", config_dir, "-a", phone, "listGroups", "-d"],
            capture_output=True,
            text=True,
            check=True
        )
        output = result.stdout
    except subprocess.CalledProcessError as e:
        click.echo(f"✗ Failed to list groups: {e.stderr}")
        exit(1)

    # Parse groups and find pending invites
    pending_invites = []
    active_groups = []

    for line in output.split("\n"):
        if not line.strip() or not line.startswith("Id:"):
            continue

        # Extract group info
        id_match = re.search(r'Id:\s*([^\s]+)', line)
        name_match = re.search(r'Name:\s+(.+?)\s+Description:', line)
        active_match = re.search(r'Active:\s*(true|false)', line)
        pending_match = re.search(r'Pending members:\s*\[([^\]]*)\]', line)

        if id_match:
            gid = id_match.group(1)
            name = name_match.group(1).strip() if name_match else "Unknown"
            is_active = active_match and active_match.group(1) == "true"
            has_pending = pending_match and phone in pending_match.group(1)

            if not is_active or has_pending:
                pending_invites.append({"id": gid, "name": name})
            else:
                active_groups.append({"id": gid, "name": name})

    # Display status
    if active_groups:
        click.echo(f"Active Groups ({len(active_groups)}):")
        for g in active_groups:
            click.echo(f"  ✓ {g['name']}")
        click.echo()

    if not pending_invites:
        click.echo("No pending group invites found.")
        exit(0)

    click.echo(f"Pending Invites ({len(pending_invites)}):")
    for g in pending_invites:
        click.echo(f"  ⏳ {g['name']} (ID: {g['id'][:20]}...)")

    if list_only:
        click.echo("\nUse --group-id to accept a specific invite, or run without --list to accept all.")
        exit(0)

    # Accept invites
    click.echo()
    invites_to_accept = pending_invites
    if group_id:
        invites_to_accept = [g for g in pending_invites if g['id'] == group_id]
        if not invites_to_accept:
            click.echo(f"✗ Group ID not found in pending invites: {group_id}")
            exit(1)

    for g in invites_to_accept:
        click.echo(f"Accepting invite for '{g['name']}'...")
        try:
            result = subprocess.run(
                ["signal-cli", "--config", config_dir, "-a", phone, "updateGroup", "-g", g['id']],
                capture_output=True,
                text=True,
                check=True
            )
            click.echo(f"  ✓ Accepted invite for '{g['name']}'")

            # Send greeting message
            try:
                subprocess.run(
                    ["signal-cli", "--config", config_dir, "-a", phone, "send", "-g", g['id'],
                     "-m", "Hello! Privacy Summarizer bot is now active and ready to generate summaries."],
                    capture_output=True,
                    check=True
                )
                click.echo(f"  ✓ Sent greeting to '{g['name']}'")
            except:
                pass  # Greeting is optional

        except subprocess.CalledProcessError as e:
            click.echo(f"  ✗ Failed to accept invite: {e.stderr}")

    click.echo("\n" + "="*70)
    click.echo("Done!")
    click.echo("="*70)


@cli.command()
@click.option('--phone', envvar='SIGNAL_PHONE_NUMBER', required=True, help='Phone number')
@click.option('--config-dir', envvar='SIGNAL_CLI_CONFIG_DIR', default='/signal-cli-config', help='Signal-CLI config directory')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
@click.option('--ollama-host', envvar='OLLAMA_HOST', default='http://localhost:11434', help='Ollama API host')
@click.option('--ollama-model', envvar='OLLAMA_MODEL', default='mistral-nemo', help='Ollama model to use')
@click.option('--group', required=True, help='Group name to summarize')
@click.option('--hours', default=24, help='Hours to look back for messages (default: 24)')
def summarize(phone, config_dir, db_path, ollama_host, ollama_model, group, hours):
    """Generate on-demand privacy-focused summary for a group (transient processing)."""
    from ..exporter.message_exporter import MessageCollector

    click.echo(f"Generating privacy-focused summary for '{group}' (last {hours} hours)...")

    # Initialize components
    signal_cli = SignalCLI(phone, config_dir)
    db_repo = DatabaseRepository(db_path)
    message_collector = MessageCollector(signal_cli, db_repo)
    ollama = OllamaClient(ollama_host, ollama_model)

    # Check Ollama availability
    if not ollama.is_available():
        click.echo("✗ Ollama is not available. Please ensure Ollama is running.")
        exit(1)

    summarizer = ChatSummarizer(ollama)

    # Sync groups to get group ID
    message_collector.sync_groups()

    # Find group by name
    groups = db_repo.get_all_groups()
    target_group = next((g for g in groups if g.name == group), None)

    if not target_group:
        click.echo(f"✗ Group '{group}' not found")
        click.echo("\nAvailable groups:")
        for g in groups:
            click.echo(f"  - {g.name}")
        exit(1)

    # Collect messages transiently
    click.echo(f"Collecting messages from '{group}'...")
    messages = message_collector.collect_recent_messages_by_time_window(
        group_id=target_group.group_id,
        hours=hours
    )

    if not messages:
        click.echo(f"✗ No messages found for '{group}' in the last {hours} hours")
        exit(0)

    # Generate privacy-focused summary
    click.echo(f"Generating privacy summary for {len(messages)} messages...")
    message_texts = [msg["content"] for msg in messages if msg["content"]]
    summary_data = summarizer.summarize_transient_messages(
        message_texts=message_texts,
        period_description=f"Last {hours} hours"
    )

    # Display summary
    click.echo(f"\n" + "="*80)
    click.echo(f"PRIVACY-FOCUSED SUMMARY: {group}")
    click.echo("="*80)
    click.echo(f"\n💬 Messages: {summary_data['message_count']}")
    click.echo(f"👥 Participants: {summary_data['participant_count']}")
    click.echo(f"💭 Sentiment: {summary_data['sentiment']}")

    if summary_data.get('topics'):
        click.echo(f"\n📋 Topics:")
        for topic in summary_data['topics']:
            click.echo(f"  • {topic}")

    if summary_data.get('summary_text'):
        click.echo(f"\n📝 Summary:")
        click.echo(f"{summary_data['summary_text']}")

    if summary_data.get('action_items'):
        click.echo(f"\n✅ Action Items:")
        for item in summary_data['action_items']:
            click.echo(f"  • {item}")

    click.echo(f"\n" + "="*80)
    click.echo("🔒 Privacy Summarizer - No data retention")
    click.echo("="*80)


def _is_group_admin(signal_cli, group_id: str, sender_uuid: str, sender_number: str = None) -> bool:
    """Check if a sender is an admin of a Signal group.

    Args:
        signal_cli: SignalCLI instance
        group_id: Signal group ID
        sender_uuid: Sender's UUID
        sender_number: Sender's phone number (optional fallback)

    Returns:
        True if sender is an admin, False otherwise
    """
    try:
        groups = signal_cli.list_groups()
        for group in groups:
            if group.get('id') == group_id:
                admins = group.get('admins', [])
                for admin in admins:
                    if admin.get('uuid') == sender_uuid:
                        return True
                    if sender_number and admin.get('phone_number') == sender_number:
                        return True
                return False
        return False
    except Exception as e:
        logger.warning(f"Failed to check admin status: {e}")
        return False  # Fail closed - assume not admin


def _is_member_of_group(signal_cli, group_id: str, sender_uuid: str, sender_number: str = None) -> bool:
    """Check if sender is a member of a Signal group.

    Args:
        signal_cli: SignalCLI instance
        group_id: Signal group ID
        sender_uuid: Sender's UUID
        sender_number: Sender's phone number (optional)

    Returns:
        True if sender is a member, False otherwise
    """
    try:
        groups = signal_cli.list_groups()
        for group in groups:
            if group.get('id') == group_id:
                members = group.get('members', [])
                for member in members:
                    if member.get('uuid') == sender_uuid:
                        return True
                    if sender_number and member.get('phone_number') == sender_number:
                        return True
                return False
        return False
    except Exception as e:
        logger.warning(f"Failed to check membership: {e}")
        return False


def _parse_quoted_args(text: str) -> list:
    """Parse arguments that may be quoted.

    Examples:
        'add "Daily Digest" "09:00"' -> ['add', 'Daily Digest', '09:00']
        'add "Morning" 09:00' -> ['add', 'Morning', '09:00']
    """
    import shlex
    try:
        return shlex.split(text)
    except ValueError:
        # Fallback to simple split if shlex fails (unmatched quotes)
        return text.split()


def _handle_schedule_command(
    message_text: str,
    group_id: str,
    source_uuid: str,
    source_number: str,
    db_repo,
    signal_cli,
    send_signal_message,
    ollama_client,
    scheduler=None
):
    """Handle the !schedule command and its subcommands.

    Args:
        message_text: Full message text (e.g., '!schedule add "Daily" "09:00"')
        group_id: Current group's Signal ID
        source_uuid: Sender's UUID
        source_number: Sender's phone number
        db_repo: DatabaseRepository instance
        signal_cli: SignalCLI instance
        send_signal_message: Function to send messages
        ollama_client: OllamaClient instance (for error help)
        scheduler: ExportScheduler instance (for reloading schedules)
    """
    import os
    import re
    import pytz
    from src.utils.message_utils import anonymize_group_id

    # Parse the command
    text = message_text.strip()
    # Remove "!schedule" prefix
    if text.lower().startswith("!schedule"):
        text = text[9:].strip()

    args = _parse_quoted_args(text) if text else []
    subcommand = args[0].lower() if args else "list"

    # Get current group info
    current_group = db_repo.get_group_by_id(group_id)
    if not current_group:
        send_signal_message(group_id, "Error: Group not found in database. Try syncing groups first.")
        return

    # Get power mode and check admin status for write operations
    power_mode = db_repo.get_group_power_mode(group_id)
    is_admin = _is_group_admin(signal_cli, group_id, source_uuid, source_number)

    def check_write_permission() -> bool:
        """Check if user has permission for write operations."""
        if power_mode == "admins" and not is_admin:
            send_signal_message(group_id, "🔒 This command is admin-only. Ask a room admin to run it.")
            return False
        return True

    # Handle subcommands
    if subcommand in ("list", ""):
        # List schedules (anyone can view)
        schedules = db_repo.get_schedules_for_group(group_id)
        if not schedules:
            help_text = """📅 No schedules for this group.

Create one:
!schedule add "Name" ["Target"] ["HH:MM"] ["Timezone"]

Examples:
!schedule add "Daily Digest"
!schedule add "Evening" "18:00"
!schedule add "Cross-Post" "Other Group" "09:00" "America/Chicago\""""
            send_signal_message(group_id, help_text)
        else:
            lines = ["📅 Schedules for this group:\n"]
            for s in schedules:
                target_hash = anonymize_group_id(s.target_group.group_id)
                status = "✅" if s.enabled else "⏸️"
                lines.append(f'{status} "{s.name}" → {target_hash} at {", ".join(s.schedule_times)} {s.timezone}')
            lines.append("\nManage: !schedule [add|remove|enable|disable] \"name\"")
            send_signal_message(group_id, "\n".join(lines))

    elif subcommand == "add":
        if not check_write_permission():
            return

        # Parse: !schedule add "Name" ["Target"] ["HH:MM"] ["Timezone"] [simple]
        if len(args) < 2:
            send_signal_message(group_id, 'Usage: !schedule add "Name" ["Target Group"] ["HH:MM"] ["Timezone"] [simple]')
            return

        schedule_name = args[1]

        # Check if schedule name already exists
        existing = db_repo.get_scheduled_summary_by_name(schedule_name)
        if existing:
            send_signal_message(group_id, f'❌ Schedule "{schedule_name}" already exists.')
            return

        # Parse optional arguments
        target_group = current_group  # Default: post back to same group
        schedule_time = "09:00"
        timezone = os.getenv("TIMEZONE", "UTC")
        detail_mode = True  # Default: detailed summaries

        # Determine what the remaining arguments are
        remaining_args = args[2:]
        for arg in remaining_args:
            # Check if it's the "simple" keyword
            if arg.lower() == "simple":
                detail_mode = False
            # Check if it's a time (HH:MM pattern)
            elif re.match(r'^\d{1,2}:\d{2}$', arg):
                schedule_time = arg
                # Normalize to HH:MM
                parts = arg.split(':')
                schedule_time = f"{int(parts[0]):02d}:{parts[1]}"
            # Check if it's a timezone (contains /)
            elif '/' in arg:
                try:
                    pytz.timezone(arg)
                    timezone = arg
                except pytz.UnknownTimeZoneError:
                    send_signal_message(group_id, f'❌ Unknown timezone: {arg}')
                    return
            # Otherwise assume it's a target group
            else:
                found_group, error = db_repo.find_group_by_name_or_hash(arg)
                if error:
                    send_signal_message(group_id, f'❌ {error}')
                    return
                # Check if sender is a member of target group
                if found_group.group_id != group_id:
                    if not _is_member_of_group(signal_cli, found_group.group_id, source_uuid, source_number):
                        send_signal_message(group_id, f'❌ You must be a member of the target group.')
                        return
                target_group = found_group

        # Validate time format
        try:
            parts = schedule_time.split(':')
            hour, minute = int(parts[0]), int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError()
            schedule_time = f"{hour:02d}:{minute:02d}"
        except (ValueError, IndexError):
            send_signal_message(group_id, '❌ Invalid time format. Use HH:MM (24-hour)')
            return

        # Get retention period (matches group's retention setting)
        retention_hours = db_repo.get_group_retention_hours(group_id)

        # Create the schedule
        try:
            schedule = db_repo.create_scheduled_summary(
                name=schedule_name,
                source_group_id=current_group.id,
                target_group_id=target_group.id,
                schedule_times=[schedule_time],
                timezone=timezone,
                summary_period_hours=retention_hours,  # Summary covers retention period
                schedule_type="daily",
                retention_hours=retention_hours,
                detail_mode=detail_mode,
                enabled=True
            )
            target_hash = anonymize_group_id(target_group.group_id)
            mode_str = "detailed" if detail_mode else "simple"
            send_signal_message(group_id,
                f'✅ Created schedule "{schedule_name}"\n'
                f'→ Posts to {target_hash} at {schedule_time} {timezone}\n'
                f'→ Summarizes last {retention_hours}h of messages ({mode_str} mode)'
            )
            # Reload scheduler to pick up new schedule
            if scheduler:
                scheduler.reload_schedules()
        except Exception as e:
            logger.error(f"Failed to create schedule: {e}")
            send_signal_message(group_id, f'❌ Failed to create schedule: {str(e)[:100]}')

    elif subcommand in ("remove", "delete", "del"):
        if not check_write_permission():
            return

        if len(args) < 2:
            send_signal_message(group_id, 'Usage: !schedule remove "Name"')
            return

        schedule_name = args[1]
        schedule = db_repo.get_scheduled_summary_by_name(schedule_name)

        if not schedule:
            send_signal_message(group_id, f'❌ Schedule "{schedule_name}" not found.')
            return

        # Verify it belongs to this group
        if schedule.source_group.group_id != group_id:
            send_signal_message(group_id, f'❌ Schedule "{schedule_name}" is not for this group.')
            return

        db_repo.delete_scheduled_summary(schedule.id)
        send_signal_message(group_id, f'✅ Deleted schedule "{schedule_name}"')
        # Reload scheduler to remove deleted schedule
        if scheduler:
            scheduler.reload_schedules()

    elif subcommand == "enable":
        if not check_write_permission():
            return

        if len(args) < 2:
            send_signal_message(group_id, 'Usage: !schedule enable "Name"')
            return

        schedule_name = args[1]
        schedule = db_repo.get_scheduled_summary_by_name(schedule_name)

        if not schedule:
            send_signal_message(group_id, f'❌ Schedule "{schedule_name}" not found.')
            return

        if schedule.source_group.group_id != group_id:
            send_signal_message(group_id, f'❌ Schedule "{schedule_name}" is not for this group.')
            return

        if schedule.enabled:
            send_signal_message(group_id, f'Schedule "{schedule_name}" is already enabled.')
            return

        db_repo.update_scheduled_summary(schedule.id, enabled=True)
        send_signal_message(group_id, f'✅ Enabled schedule "{schedule_name}"')
        # Reload scheduler to pick up enabled schedule
        if scheduler:
            scheduler.reload_schedules()

    elif subcommand == "disable":
        if not check_write_permission():
            return

        if len(args) < 2:
            send_signal_message(group_id, 'Usage: !schedule disable "Name"')
            return

        schedule_name = args[1]
        schedule = db_repo.get_scheduled_summary_by_name(schedule_name)

        if not schedule:
            send_signal_message(group_id, f'❌ Schedule "{schedule_name}" not found.')
            return

        if schedule.source_group.group_id != group_id:
            send_signal_message(group_id, f'❌ Schedule "{schedule_name}" is not for this group.')
            return

        if not schedule.enabled:
            send_signal_message(group_id, f'Schedule "{schedule_name}" is already disabled.')
            return

        db_repo.update_scheduled_summary(schedule.id, enabled=False)
        send_signal_message(group_id, f'⏸️ Disabled schedule "{schedule_name}"')
        # Reload scheduler to remove disabled schedule
        if scheduler:
            scheduler.reload_schedules()

    else:
        # Unknown subcommand - try to provide helpful error via Ollama
        try:
            if ollama_client and ollama_client.is_available():
                error_prompt = f"""The user tried to run this schedule command: !schedule {text}

The valid subcommands are:
- !schedule (or !schedule list) - Show schedules for this group
- !schedule add "Name" ["Target Group"] ["HH:MM"] ["Timezone"] - Create a schedule
- !schedule remove "Name" - Delete a schedule
- !schedule enable "Name" - Enable a schedule
- !schedule disable "Name" - Disable a schedule

Arguments in quotes can contain spaces. Time is 24-hour format (e.g., "09:00", "18:30").
Timezone uses IANA format (e.g., "America/Chicago", "Europe/London").

Generate a short, helpful error message (2-3 sentences max) explaining what might be wrong and showing a correct example. Be friendly."""

                response = ollama_client.chat(error_prompt, [])
                if response:
                    send_signal_message(group_id, response[:500])  # Limit length
                    return
        except Exception as e:
            logger.warning(f"Ollama error help failed: {e}")

        # Fallback error message
        send_signal_message(group_id,
            f'❌ Unknown subcommand: {subcommand}\n\n'
            'Usage:\n'
            '!schedule - List schedules\n'
            '!schedule add "Name" - Create schedule\n'
            '!schedule remove "Name" - Delete schedule\n'
            '!schedule enable/disable "Name"'
        )


def _handle_unknown_command(
    command_text: str,
    group_id: str,
    send_signal_message,
    ollama_client=None
):
    """Handle unrecognized ! commands with helpful suggestions.

    Uses Ollama (if available) to generate intelligent error messages
    with typo detection and command suggestions. Falls back to a static
    error message if Ollama is unavailable.

    Args:
        command_text: The unrecognized command (e.g., '!sumary')
        group_id: Current group's Signal ID
        send_signal_message: Function to send messages
        ollama_client: OllamaClient instance (for intelligent suggestions)
    """
    try:
        if ollama_client and ollama_client.is_available():
            error_prompt = f"""The user tried to run this command in a Signal group: {command_text}

Valid commands are:
- !help - Show available commands
- !status - Check bot status and retention setting
- !summary [hours] [detail] - Generate summary
- !opt-out / !opt-in - Control message collection for yourself
- !retention [hours] - View/set retention period (admin)
- !schedule [add|remove|enable|disable] - Manage scheduled summaries (admin)
- !purge-mode [on|off] - Control if messages are purged after summary (admin)
- !power [admins|everyone] - Set who can run config commands (admin)
- !!!purge - Delete all stored messages (admin)

Generate a short, helpful error message (2-3 sentences max) that:
1. Notes the command wasn't recognized
2. Suggests the most likely intended command if it looks like a typo
3. Points them to !help for full command list

Be friendly and concise."""

            response = ollama_client.chat(error_prompt, [])
            if response:
                send_signal_message(group_id, response[:500])  # Limit length
                return
    except Exception as e:
        logger.warning(f"Ollama error help failed: {e}")

    # Fallback error message
    send_signal_message(group_id,
        f'❓ Unknown command: {command_text.split()[0]}\n\n'
        'Type !help for available commands.'
    )


@cli.command()
@click.option('--phone', envvar='SIGNAL_PHONE_NUMBER', required=True, help='Phone number')
@click.option('--config-dir', envvar='SIGNAL_CLI_CONFIG_DIR', default='/signal-cli-config', help='Signal-CLI config directory')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
@click.option('--ollama-host', envvar='OLLAMA_HOST', default='http://localhost:11434', help='Ollama API host')
@click.option('--ollama-model', envvar='OLLAMA_MODEL', default='mistral-nemo', help='Ollama model to use')
@click.option('--auto-accept-invites/--no-auto-accept-invites', envvar='AUTO_ACCEPT_GROUP_INVITES', default=True, help='Auto-accept group invites')
def daemon(phone, config_dir, db_path, ollama_host, ollama_model, auto_accept_invites):
    """Run Privacy Summarizer daemon with real-time message handling."""
    from ..exporter.summary_poster import SummaryPoster
    from ..exporter.message_exporter import MessageCollector
    from ..dm.handler import DMHandler
    import threading
    import subprocess
    import json

    click.echo("Starting Privacy Summarizer daemon (real-time mode)...")

    # Initialize components
    signal_cli = SignalCLI(phone, config_dir)
    db_repo = DatabaseRepository(db_path)
    ollama = OllamaClient(ollama_host, ollama_model)
    summarizer = ChatSummarizer(ollama)

    # Initialize DM handler
    dm_handler = DMHandler(ollama, signal_cli, db_repo)

    # Initialize message collector with DM handler
    message_collector = MessageCollector(signal_cli, db_repo, dm_handler=dm_handler)

    # Sync groups from Signal on startup
    try:
        group_count = message_collector.sync_groups()
        click.echo(f"✓ Synced {group_count} groups from Signal")
    except Exception as e:
        click.echo(f"⚠ Warning: Failed to sync groups: {e}")

    summary_poster = SummaryPoster(signal_cli, summarizer, db_repo, message_collector)

    # Check Ollama
    if not ollama.is_available():
        click.echo("⚠ Warning: Ollama is not available. Summaries will fail until Ollama is running.")

    # Setup scheduler (purge job and scheduled summaries only)
    scheduler = ExportScheduler(
        summary_poster=summary_poster,
        db_repo=db_repo
    )

    # Display configured schedules
    scheduled_summaries = db_repo.get_enabled_scheduled_summaries()

    click.echo(f"\n🔒 Privacy Summarizer - Real-Time Message Handling")
    click.echo(f"\n🗑️  Retention Purge: Every {scheduler.purge_interval_hours} hour(s)")
    click.echo(f"⏰ Default Message Retention: {scheduler.default_message_retention_hours} hours")

    # Helper function to send messages via signal-cli
    def send_signal_message(group_id: str, message: str) -> bool:
        """Send a message to a Signal group using signal-cli directly.

        Uses stdin for the message to avoid command-line length limits and
        special character issues with long messages.
        """
        try:
            # Use stdin for message content to avoid command-line length limits
            result = subprocess.run(
                ["signal-cli", "--config", config_dir, "-a", phone,
                 "send", "-g", group_id, "--message-from-stdin"],
                input=message,
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                logger.error(f"Failed to send message: {result.stderr}")
                return False
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    # Setup summarize callback
    def summarize_callback(group_id: str, hours: int, detail: bool = False) -> str:
        """Generate summary for a group via !summary command.

        Args:
            group_id: Signal group ID
            hours: Number of hours to look back
            detail: If True, generate detailed summary with action items
        """
        try:
            # Get messages from database with reaction data
            from datetime import datetime, timedelta
            since = datetime.utcnow() - timedelta(hours=hours)
            messages_with_reactions = db_repo.get_messages_with_reactions_for_group(
                group_id, since=since
            )

            if not messages_with_reactions:
                return f"No messages found in the last {hours} hours."

            # Filter out command messages (belt-and-suspenders)
            filtered_messages = [
                m for m in messages_with_reactions
                if m.get('content') and not m['content'].strip().startswith('!')
            ]

            if not filtered_messages:
                return f"No messages found in the last {hours} hours."

            # Count actual stats from database (not AI estimates)
            actual_msg_count = len(filtered_messages)

            # Require minimum messages to avoid AI hallucination
            MIN_MESSAGES_FOR_SUMMARY = 3
            if actual_msg_count < MIN_MESSAGES_FOR_SUMMARY:
                return f"Only {actual_msg_count} message(s) in the last {hours} hours. Need at least {MIN_MESSAGES_FOR_SUMMARY} for a meaningful summary."

            # Generate summary with reaction context
            period_desc = f"the last {hours} hours"
            summary_data = summarizer.summarize_transient_messages(
                message_texts=[],  # Not used when messages_with_reactions provided
                period_description=period_desc,
                messages_with_reactions=filtered_messages,
                detail=detail
            )

            # Purge summarized messages (if purge_on_summary is enabled for this group)
            if db_repo.get_group_purge_on_summary(group_id):
                try:
                    purged = db_repo.purge_messages_for_group(group_id, before=datetime.utcnow())
                    logger.info(f"Purged {purged} messages after summarization")
                except Exception as e:
                    logger.error(f"Failed to purge messages: {e}")
            else:
                logger.info("Skipping post-summary purge (purge_on_summary=False)")

            # Format summary for Signal message
            if isinstance(summary_data, dict):
                result = f"📊 Summary ({hours}h)\n"

                # Statistics (use actual counts from database, not AI estimates)
                sentiment = summary_data.get('sentiment', 'neutral')

                if detail:
                    # Detailed mode: show stats on separate lines
                    result += f"\n💬 Messages: {actual_msg_count}\n"
                    if summary_data.get('participant_count'):
                        result += f"👥 Participants: {summary_data['participant_count']}\n"
                    result += f"💭 Sentiment: {sentiment}\n"
                else:
                    # Simple mode: compact stats on one line
                    result += f"\n📈 {actual_msg_count} messages"
                    if summary_data.get('participant_count'):
                        result += f" • {summary_data['participant_count']} participant(s)"
                    result += f" • {sentiment}\n"

                # Topics
                topics = summary_data.get('topics', [])
                if topics:
                    result += f"\n📋 Topics:\n"
                    for topic in topics[:5]:  # Limit to 5 topics
                        result += f"  • {topic}\n"

                # Summary text
                if summary_data.get('summary_text'):
                    result += f"\n📝 Summary:\n{summary_data['summary_text']}\n"

                # Action items only in detail mode
                if detail:
                    action_items = summary_data.get('action_items', [])
                    if action_items:
                        result += f"\n✅ Action Items:\n"
                        for item in action_items:
                            result += f"  • {item}\n"

                return result.strip()
            return str(summary_data)
        except Exception as e:
            logger.error(f"Summarize callback failed: {e}")
            return f"Failed to generate summary: {str(e)[:100]}"

    # Track running state
    running = True

    # Start message polling in background thread
    def realtime_loop():
        """Poll for messages using signal-cli directly, process commands."""
        nonlocal running
        logger.info("Real-time message loop started (using signal-cli receive)")

        # Track processed message timestamps for deduplication
        # Signal-cli may return the same message multiple times
        processed_timestamps = set()
        MAX_PROCESSED_CACHE = 1000  # Limit cache size to prevent memory growth

        while running:
            try:
                # Use signal-cli directly to receive messages (with short timeout)
                # Note: -o json is a global option, not a receive subcommand option
                result = subprocess.run(
                    ["signal-cli", "--config", config_dir, "-a", phone,
                     "-o", "json", "receive", "--timeout", "5"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.stdout:
                    # Parse JSON output (one JSON object per line)
                    for line in result.stdout.strip().split('\n'):
                        if not line:
                            continue
                        try:
                            envelope = json.loads(line)

                            # Extract message details from signal-cli JSON output
                            env = envelope.get('envelope', {})
                            data_message = env.get('dataMessage', {})

                            message_text = data_message.get('message')
                            group_info = data_message.get('groupInfo', {})
                            group_id = group_info.get('groupId')
                            # sourceUuid is the preferred field, fall back to source
                            source_uuid = env.get('sourceUuid') or env.get('source')
                            timestamp = env.get('timestamp', 0)

                            # Extract expiresInSeconds for auto-retention
                            expires_in_seconds = data_message.get('expiresInSeconds', 0)

                            # Deduplicate messages by timestamp
                            if timestamp in processed_timestamps:
                                logger.debug(f"Skipping duplicate message (timestamp={timestamp})")
                                continue
                            processed_timestamps.add(timestamp)

                            # Clean up old timestamps to prevent memory growth
                            if len(processed_timestamps) > MAX_PROCESSED_CACHE:
                                # Keep only the most recent half
                                sorted_ts = sorted(processed_timestamps)
                                processed_timestamps.clear()
                                processed_timestamps.update(sorted_ts[MAX_PROCESSED_CACHE // 2:])

                            if message_text:
                                # Skip messages from the bot itself (belt-and-suspenders)
                                source_number = env.get('sourceNumber') or env.get('source', '')
                                if source_number == phone:
                                    logger.debug(f"Skipping bot's own message")
                                    continue

                                # Handle DMs separately - route to DM handler
                                if not group_id:
                                    if source_number:
                                        logger.info(f"Received DM from {source_number[:6]}...")
                                        try:
                                            dm_handler.handle_dm(source_number, message_text, timestamp)
                                            logger.info(f"Responded to DM from {source_number[:6]}...")
                                        except Exception as e:
                                            logger.error(f"Error handling DM: {e}")
                                    continue

                                logger.info(f"Received message in group {group_id[:20]}...")

                                # Check if this is a command (don't store commands to database)
                                text_lower = message_text.strip().lower()
                                is_command = text_lower.startswith('!')

                                # Store non-command messages to database (respecting opt-out)
                                if group_id and source_uuid and not is_command:
                                    # Check if user has opted out of message collection
                                    if db_repo.is_user_opted_out(group_id, source_uuid):
                                        logger.debug(f"Skipping message from opted-out user {source_uuid[:8]}...")
                                    else:
                                        try:
                                            # Auto-update retention from Signal's disappearing messages setting
                                            settings = db_repo.get_group_settings(group_id)
                                            if settings is None or settings.source == "signal":
                                                if expires_in_seconds > 0:
                                                    retention_hours = max(1, expires_in_seconds // 3600)
                                                else:
                                                    retention_hours = 48  # Default when no disappearing messages

                                                current = db_repo.get_group_retention_hours(group_id)
                                                if retention_hours != current:
                                                    db_repo.set_group_retention_hours(group_id, retention_hours, source="signal")
                                                    logger.info(f"Auto-set retention for {group_id[:20]}... to {retention_hours}h from Signal")

                                            db_repo.store_message(
                                                signal_timestamp=timestamp,
                                                sender_uuid=source_uuid,
                                                group_id=group_id,
                                                content=message_text
                                            )
                                        except Exception as e:
                                            logger.error(f"Failed to store message: {e}")

                                # Process commands
                                if text_lower == "!help" and group_id:
                                    logger.info("Processing !help command")
                                    help_text = """📖 Commands

!help - This help
!status - Bot status
!summary [hrs] [detail] - Generate summary (detail = verbose mode)
!opt-out - Stop collecting your messages
!opt-in - Resume collecting your messages
!retention - View/set retention 🔒
!purge-mode - Keep/delete messages after summary 🔒
!schedule - Manage schedules 🔒
!power - View/set permissions 🔒
!!!purge - Delete all messages 🔒

🔒 = Admin-only
📖 Docs: https://next.maidan.cloud/apps/collectives/p/SCXCe4p3RDexBZC/Privacy-Summarizer-Docs-4"""
                                    send_signal_message(group_id, help_text)
                                elif text_lower == "!status" and group_id:
                                    logger.info("Processing !status command")
                                    message_counts = db_repo.get_message_count_by_group()
                                    count = message_counts.get(group_id, 0)
                                    retention_hours = db_repo.get_group_retention_hours(group_id)
                                    purge_on = db_repo.get_group_purge_on_summary(group_id)
                                    purge_mode = "on" if purge_on else "off"
                                    status_msg = f"""📊 Status

✅ Service: Active
💬 Messages: {count} stored
⏰ Retention: {retention_hours} hours
🗑️ Purge after summary: {purge_mode}"""
                                    send_signal_message(group_id, status_msg)
                                elif text_lower.startswith("!summary") and group_id:
                                    logger.info("Processing !summary command")
                                    # Parse hours and detail from command
                                    # Syntax: !summary [hours] [detail]
                                    parts = message_text.strip().split()
                                    hours = db_repo.get_group_retention_hours(group_id)
                                    detail = False

                                    for part in parts[1:]:
                                        if part.lower() == 'detail':
                                            detail = True
                                        else:
                                            try:
                                                hours = int(part)
                                            except ValueError:
                                                pass

                                    mode_str = " (detailed)" if detail else ""
                                    send_signal_message(group_id, f"Generating summary for the last {hours} hours{mode_str}...")
                                    summary = summarize_callback(group_id, hours, detail=detail)
                                    # Split long summaries to fit within Signal's character limit
                                    logger.info(f"Summary length: {len(summary)} characters")
                                    summary_parts = split_long_message(summary)
                                    logger.info(f"Split into {len(summary_parts)} parts")
                                    for i, part in enumerate(summary_parts):
                                        logger.info(f"Sending part {i+1}/{len(summary_parts)} ({len(part)} chars)")
                                        send_signal_message(group_id, part)
                                        # Small delay between messages to maintain order
                                        if len(summary_parts) > 1:
                                            time.sleep(0.5)
                                elif text_lower == "!!!purge" and group_id:
                                    logger.info("Processing !!!purge command")
                                    # Check permission - !!!purge is a write command
                                    power_mode = db_repo.get_group_power_mode(group_id)
                                    if power_mode == "admins":
                                        is_admin = _is_group_admin(signal_cli, group_id, source_uuid, source_number)
                                        if not is_admin:
                                            send_signal_message(group_id, "🔒 This command is admin-only. Ask a room admin to run it.")
                                            continue
                                    count = db_repo.purge_all_messages_for_group(group_id)
                                    send_signal_message(group_id, f"✅ Purged {count} stored messages.")
                                elif text_lower.startswith("!power") and group_id:
                                    logger.info("Processing !power command")
                                    parts = message_text.strip().split()
                                    is_admin = _is_group_admin(signal_cli, group_id, source_uuid, source_number)

                                    if len(parts) == 1:
                                        # View current power mode (anyone can view)
                                        current = db_repo.get_group_power_mode(group_id)
                                        if current == "admins":
                                            response = "⚡ Power Level: ADMINS ONLY\n\nOnly room admins can change settings. Regular members can view but not modify."
                                        else:
                                            response = "⚡ Power Level: EVERYONE\n\nAll room members can change settings. Democracy reigns!"
                                        send_signal_message(group_id, response)
                                    elif not is_admin:
                                        # Only admins can change power mode (always)
                                        send_signal_message(group_id, "🔒 Nice try! Only admins can change power levels.")
                                    elif parts[1].lower() == "admins":
                                        db_repo.set_group_power_mode(group_id, "admins")
                                        send_signal_message(group_id, "⚡ Power Level: ADMINS ONLY\n\n🏰 The castle gates are locked! Only admins hold the keys now.")
                                    elif parts[1].lower() == "everyone":
                                        db_repo.set_group_power_mode(group_id, "everyone")
                                        send_signal_message(group_id, "⚡ Power Level: EVERYONE\n\n🎉 Power to the people! All members can now change settings.")
                                    else:
                                        send_signal_message(group_id, "Usage: !power [admins|everyone]")
                                elif text_lower.startswith("!purge-mode") and group_id:
                                    logger.info("Processing !purge-mode command")
                                    parts = message_text.strip().split()

                                    if len(parts) == 1:
                                        # View current setting (anyone can view)
                                        purge_on = db_repo.get_group_purge_on_summary(group_id)
                                        if purge_on:
                                            response = "🗑️ Purge Mode: ON\n\nMessages are deleted immediately after !summary."
                                        else:
                                            response = "🗑️ Purge Mode: OFF\n\nMessages are kept until retention period expires."
                                        send_signal_message(group_id, response)
                                    else:
                                        # Write operation - check permission
                                        power_mode = db_repo.get_group_power_mode(group_id)
                                        if power_mode == "admins":
                                            is_admin = _is_group_admin(signal_cli, group_id, source_uuid, source_number)
                                            if not is_admin:
                                                send_signal_message(group_id, "🔒 This command is admin-only. Ask a room admin to run it.")
                                                continue

                                        arg = parts[1].lower()
                                        if arg == "on":
                                            db_repo.set_group_purge_on_summary(group_id, True)
                                            send_signal_message(group_id, "🗑️ Purge Mode: ON\n\nMessages will be deleted immediately after !summary.")
                                        elif arg == "off":
                                            db_repo.set_group_purge_on_summary(group_id, False)
                                            send_signal_message(group_id, "🗑️ Purge Mode: OFF\n\nMessages will be kept until retention period expires.\nRun multiple summaries from the same messages!")
                                        else:
                                            send_signal_message(group_id, "Usage: !purge-mode [on|off]")
                                elif text_lower.startswith("!retention") and group_id:
                                    logger.info("Processing !retention command")
                                    parts = message_text.strip().split()
                                    if len(parts) == 1:
                                        # Just "!retention" - show current setting (anyone can view)
                                        hours = db_repo.get_group_retention_hours(group_id)
                                        settings = db_repo.get_group_settings(group_id)
                                        if settings and settings.source == "signal":
                                            mode = "auto"
                                        elif settings and settings.source == "command":
                                            mode = "fixed"
                                        else:
                                            mode = "default"
                                        send_signal_message(group_id,
                                            f"⏰ Retention: {hours}h ({mode})\n"
                                            f"Set: !retention [hours] or !retention auto")
                                    else:
                                        # Write operation - check permission
                                        power_mode = db_repo.get_group_power_mode(group_id)
                                        if power_mode == "admins":
                                            is_admin = _is_group_admin(signal_cli, group_id, source_uuid, source_number)
                                            if not is_admin:
                                                send_signal_message(group_id, "🔒 This command is admin-only. Ask a room admin to run it.")
                                                continue

                                        if parts[1].lower() in ("signal", "auto"):
                                            # "!retention auto" - re-enable following Signal's setting
                                            current_hours = db_repo.get_group_retention_hours(group_id)
                                            db_repo.set_group_retention_hours(group_id, current_hours, source="signal")
                                            send_signal_message(group_id, f"✅ Auto mode: {current_hours}h\nSyncs with Signal's disappearing messages")
                                        else:
                                            # "!retention [hours]" - set fixed retention
                                            try:
                                                hours = int(parts[1])
                                                if not 1 <= hours <= 168:
                                                    raise ValueError()
                                                db_repo.set_group_retention_hours(group_id, hours, source="command")
                                                send_signal_message(group_id, f"✅ Fixed: {hours}h\nWon't change with Signal settings")
                                            except ValueError:
                                                send_signal_message(group_id, "❌ Use 1-168 hours or 'auto'")
                                elif text_lower == "!opt-out" and group_id:
                                    logger.info("Processing !opt-out command")
                                    # Anyone can opt themselves out - no admin check needed
                                    if not source_uuid:
                                        send_signal_message(group_id, "Unable to process - user ID not available.")
                                        continue

                                    # Set opt-out status
                                    db_repo.set_user_opt_out(group_id, source_uuid, opted_out=True)

                                    # Immediately delete their existing messages
                                    deleted_count = db_repo.delete_user_messages_in_group(group_id, source_uuid)

                                    if deleted_count > 0:
                                        send_signal_message(group_id, f"Opted out. {deleted_count} messages deleted.")
                                    else:
                                        send_signal_message(group_id, "Opted out. Your messages will no longer be stored.")
                                elif text_lower == "!opt-in" and group_id:
                                    logger.info("Processing !opt-in command")
                                    # Anyone can opt themselves back in
                                    if not source_uuid:
                                        send_signal_message(group_id, "Unable to process - user ID not available.")
                                        continue

                                    # Check if they were actually opted out
                                    was_opted_out = db_repo.is_user_opted_out(group_id, source_uuid)

                                    # Set opt-in status
                                    db_repo.set_user_opt_out(group_id, source_uuid, opted_out=False)

                                    if was_opted_out:
                                        send_signal_message(group_id, "Opted in. Your messages will now be collected.")
                                    else:
                                        send_signal_message(group_id, "Already opted in.")
                                elif text_lower.startswith("!schedule") and group_id:
                                    logger.info("Processing !schedule command")
                                    _handle_schedule_command(
                                        message_text, group_id, source_uuid, source_number,
                                        db_repo, signal_cli, send_signal_message, ollama, scheduler
                                    )
                                elif is_command and group_id:
                                    # Unrecognized command - provide helpful suggestion
                                    logger.info(f"Unknown command: {message_text}")
                                    _handle_unknown_command(
                                        message_text, group_id, send_signal_message, ollama
                                    )

                                # Check for group invite (auto-accept if enabled)
                                if auto_accept_invites and group_info.get('type') == 'UPDATE':
                                    logger.info(f"Received group invite for {group_id[:20]}...")
                                    try:
                                        accept_result = subprocess.run(
                                            ["signal-cli", "--config", config_dir, "-a", phone,
                                             "updateGroup", "-g", group_id],
                                            capture_output=True,
                                            text=True,
                                            timeout=30
                                        )
                                        if accept_result.returncode == 0:
                                            logger.info(f"Auto-accepted group invite: {group_id[:20]}")
                                            send_signal_message(group_id, "Hello! Privacy Summarizer bot is now active and ready to generate summaries.")
                                    except Exception as e:
                                        logger.error(f"Failed to auto-accept invite: {e}")

                        except json.JSONDecodeError as e:
                            logger.debug(f"Failed to parse JSON line: {e}")

            except subprocess.TimeoutExpired:
                logger.debug("Receive timeout (normal)")
            except Exception as e:
                logger.error(f"Real-time loop error: {e}")

            import time as time_module
            time_module.sleep(1)  # Brief pause between receive cycles
        logger.info("Real-time message loop stopped")

    realtime_thread = threading.Thread(target=realtime_loop, daemon=True)
    realtime_thread.start()

    click.echo("✓ Real-time message handling enabled")
    click.echo("✓ Commands enabled: !help, !summary, !status, !opt-out, !opt-in, !retention, !purge-mode, !schedule, !power, !!!purge")
    if auto_accept_invites:
        click.echo("✓ Auto-accept group invites enabled")

    click.echo(f"\n✓ Enabled Scheduled Summaries: {len(scheduled_summaries)}")

    if scheduled_summaries:
        for schedule in scheduled_summaries:
            schedule_type = getattr(schedule, 'schedule_type', 'daily')
            if schedule_type == 'weekly':
                day_of_week = getattr(schedule, 'schedule_day_of_week', 0)
                day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                day_name = day_names[day_of_week] if 0 <= day_of_week <= 6 else f"Day {day_of_week}"
                time_str = schedule.schedule_times[0] if schedule.schedule_times else "Unknown"
                click.echo(f"  - {schedule.name}: {day_name}s at {time_str} ({schedule.timezone})")
            else:
                times_str = ', '.join(schedule.schedule_times)
                click.echo(f"  - {schedule.name}: Daily at {times_str} ({schedule.timezone})")
    else:
        click.echo(f"\n⚠ No scheduled summaries configured.")
        click.echo(f"   Use 'schedule-summary add' to create schedules")

    # Start scheduler
    scheduler.start()
    click.echo("\n✓ Privacy Summarizer daemon started. Press Ctrl+C to stop.\n")

    try:
        # Keep running
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        click.echo("\nStopping daemon...")
        running = False
        scheduler.stop()
        click.echo("✓ Privacy Summarizer daemon stopped")


@cli.group()
def schedule_summary():
    """Manage scheduled summaries from one group to another."""
    pass


@schedule_summary.command(name='add')
@click.option('--name', required=True, help='Name for this scheduled summary')
@click.option('--source-group', required=True, help='Source group name to summarize')
@click.option('--target-group', required=True, help='Target group name to post summaries')
@click.option('--type', 'schedule_type', type=click.Choice(['daily', 'weekly']), default='daily', help='Schedule type: daily or weekly (default: daily)')
@click.option('--times', multiple=True, help='Schedule times for daily summaries in HH:MM format (e.g., --times 08:00 --times 20:00)')
@click.option('--time', 'weekly_time', help='Schedule time for weekly summaries in HH:MM format (e.g., --time 20:00)')
@click.option('--day-of-week', type=click.Choice(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']), help='Day of week for weekly summaries')
@click.option('--timezone', default='UTC', help='Timezone for scheduled times (e.g., America/Chicago, US/Central)')
@click.option('--period-hours', default=24, type=int, help='Hours to look back for summary (default: 24 for daily, 168 for weekly)')
@click.option('--retention-hours', default=48, type=int, help='Hours to retain messages for this schedule (default: 48, use higher for weekly)')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
@click.option('--phone', envvar='SIGNAL_PHONE_NUMBER', required=True, help='Phone number')
@click.option('--config-dir', envvar='SIGNAL_CLI_CONFIG_DIR', default='/signal-cli-config', help='Signal-CLI config directory')
def add_schedule(name, source_group, target_group, schedule_type, times, weekly_time, day_of_week, timezone, period_hours, retention_hours, db_path, phone, config_dir):
    """Add a new scheduled summary."""
    import pytz

    try:
        # Validate based on schedule type
        if schedule_type == 'weekly':
            # Weekly validation
            if not weekly_time:
                click.echo("✗ Weekly schedules require --time option")
                exit(1)
            if not day_of_week:
                click.echo("✗ Weekly schedules require --day-of-week option")
                exit(1)

            # Validate time format
            try:
                hour, minute = map(int, weekly_time.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError()
            except:
                click.echo(f"✗ Invalid time format: {weekly_time}. Must be HH:MM (e.g., 08:00, 20:00)")
                exit(1)

            # Map day name to number (0=Monday, 6=Sunday)
            day_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                'friday': 4, 'saturday': 5, 'sunday': 6
            }
            day_of_week_num = day_map[day_of_week]

            # Use weekly_time as the single schedule time
            schedule_times = [weekly_time]

            # Default period_hours to 168 (7 days) if not specified
            if period_hours == 24:  # Default wasn't changed
                period_hours = 168
        else:
            # Daily validation
            if not times:
                click.echo("✗ Daily schedules require --times option (can specify multiple)")
                exit(1)

            # Validate times format
            for time_str in times:
                try:
                    hour, minute = map(int, time_str.split(":"))
                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                        raise ValueError()
                except:
                    click.echo(f"✗ Invalid time format: {time_str}. Must be HH:MM (e.g., 08:00, 20:00)")
                    exit(1)

            schedule_times = list(times)
            day_of_week_num = None

        # Default retention_hours for weekly to 168 (7 days) if not changed from default
        if schedule_type == 'weekly' and retention_hours == 48:
            retention_hours = 168

        # Validate timezone
        try:
            pytz.timezone(timezone)
        except Exception:
            click.echo(f"✗ Invalid timezone: {timezone}")
            click.echo(f"\nValid timezone examples: UTC, America/New_York, America/Chicago, America/Los_Angeles, US/Central, US/Eastern")
            exit(1)

        # Initialize components
        db_repo = DatabaseRepository(db_path)
        signal_cli = SignalCLI(phone, config_dir)

        # Get groups
        all_groups = db_repo.get_all_groups()
        source = None
        target = None

        for group in all_groups:
            if group.name.lower() == source_group.lower():
                source = group
            if group.name.lower() == target_group.lower():
                target = group

        if not source:
            click.echo(f"✗ Source group '{source_group}' not found")
            click.echo("\nAvailable groups:")
            for g in all_groups:
                click.echo(f"  - {g.name}")
            exit(1)

        if not target:
            click.echo(f"✗ Target group '{target_group}' not found")
            click.echo("\nAvailable groups:")
            for g in all_groups:
                click.echo(f"  - {g.name}")
            exit(1)

        # Create the scheduled summary
        schedule = db_repo.create_scheduled_summary(
            name=name,
            source_group_id=source.id,
            target_group_id=target.id,
            schedule_times=schedule_times,
            timezone=timezone,
            summary_period_hours=period_hours,
            schedule_type=schedule_type,
            schedule_day_of_week=day_of_week_num,
            retention_hours=retention_hours,
            enabled=True
        )

        click.echo(f"\n✓ Created {schedule_type} scheduled summary '{name}'")
        click.echo(f"  Source: {source.name}")
        click.echo(f"  Target: {target.name}")
        if schedule_type == 'weekly':
            click.echo(f"  Schedule: {day_of_week.title()}s at {weekly_time} ({timezone})")
            click.echo(f"  Period: {period_hours} hours (~{period_hours//24} days)")
        else:
            click.echo(f"  Times: {', '.join(schedule_times)} ({timezone})")
            click.echo(f"  Period: {period_hours} hours")
        click.echo(f"  Retention: {retention_hours} hours")
        click.echo(f"\nNote: Restart the daemon to activate this schedule:")
        click.echo(f"  docker-compose restart")

    except Exception as e:
        click.echo(f"✗ Error creating scheduled summary: {e}")
        logger.error(f"Error creating scheduled summary: {e}", exc_info=True)
        exit(1)


@schedule_summary.command(name='list')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
@click.option('--enabled-only', is_flag=True, help='Show only enabled schedules')
def list_schedules(db_path, enabled_only):
    """List all scheduled summaries."""
    db_repo = DatabaseRepository(db_path)

    if enabled_only:
        schedules = db_repo.get_enabled_scheduled_summaries()
        title = "Enabled Scheduled Summaries"
    else:
        schedules = db_repo.get_all_scheduled_summaries()
        title = "All Scheduled Summaries"

    click.echo(f"\n=== {title} ===\n")

    if not schedules:
        click.echo("No scheduled summaries found.")
        return

    for schedule in schedules:
        status_icon = "✓" if schedule.enabled else "✗"
        schedule_type = getattr(schedule, 'schedule_type', 'daily')
        click.echo(f"{status_icon} [{schedule.id}] {schedule.name} ({schedule_type})")
        click.echo(f"    Source: {schedule.source_group.name}")
        click.echo(f"    Target: {schedule.target_group.name}")

        if schedule_type == 'weekly':
            day_of_week = getattr(schedule, 'schedule_day_of_week', None)
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            day_name = day_names[day_of_week] if day_of_week is not None and 0 <= day_of_week <= 6 else 'Unknown'
            time_str = schedule.schedule_times[0] if schedule.schedule_times else 'Unknown'
            click.echo(f"    Schedule: {day_name}s at {time_str} ({schedule.timezone})")
        else:
            click.echo(f"    Times: {', '.join(schedule.schedule_times)} ({schedule.timezone})")

        click.echo(f"    Period: {schedule.summary_period_hours} hours")
        click.echo(f"    Enabled: {'Yes' if schedule.enabled else 'No'}")
        if schedule.last_run:
            click.echo(f"    Last Run: {schedule.last_run.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        click.echo()


@schedule_summary.command(name='update')
@click.option('--id', 'schedule_id', required=True, type=int, help='Schedule ID to update')
@click.option('--times', multiple=True, help='New schedule times in HH:MM format')
@click.option('--timezone', help='New timezone')
@click.option('--period-hours', type=int, help='New period in hours')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
def update_schedule(schedule_id, times, timezone, period_hours, db_path):
    """Update a scheduled summary."""
    import pytz

    try:
        db_repo = DatabaseRepository(db_path)

        # Check if schedule exists
        schedule = db_repo.get_scheduled_summary_by_id(schedule_id)
        if not schedule:
            click.echo(f"✗ Schedule ID {schedule_id} not found")
            exit(1)

        # Build update kwargs
        updates = {}

        if times:
            # Validate times format
            for time_str in times:
                try:
                    hour, minute = map(int, time_str.split(":"))
                    if not (0 <= hour <= 23 and 0 <= minute <= 59):
                        raise ValueError()
                except:
                    click.echo(f"✗ Invalid time format: {time_str}")
                    exit(1)
            updates['schedule_times'] = list(times)

        if timezone:
            # Validate timezone
            try:
                pytz.timezone(timezone)
                updates['timezone'] = timezone
            except:
                click.echo(f"✗ Invalid timezone: {timezone}")
                exit(1)

        if period_hours is not None:
            updates['summary_period_hours'] = period_hours

        if not updates:
            click.echo("✗ No updates specified. Use --times, --timezone, or --period-hours")
            exit(1)

        # Perform update
        db_repo.update_scheduled_summary(schedule_id, **updates)

        click.echo(f"\n✓ Updated schedule '{schedule.name}'")
        for key, value in updates.items():
            click.echo(f"  {key}: {value}")
        click.echo(f"\nNote: Restart the daemon to apply changes:")
        click.echo(f"  docker-compose restart")

    except Exception as e:
        click.echo(f"✗ Error updating schedule: {e}")
        logger.error(f"Error updating schedule: {e}", exc_info=True)
        exit(1)


@schedule_summary.command(name='remove')
@click.option('--id', 'schedule_id', type=int, help='Schedule ID to remove')
@click.option('--name', help='Schedule name to remove')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
@click.confirmation_option(prompt='Are you sure you want to remove this schedule?')
def remove_schedule(schedule_id, name, db_path):
    """Remove a scheduled summary."""
    db_repo = DatabaseRepository(db_path)

    if not schedule_id and not name:
        click.echo("✗ Must specify --id or --name")
        exit(1)

    # Find the schedule
    if schedule_id:
        schedule = db_repo.get_scheduled_summary_by_id(schedule_id)
    else:
        schedule = db_repo.get_scheduled_summary_by_name(name)

    if not schedule:
        click.echo(f"✗ Schedule not found")
        exit(1)

    # Delete it
    success = db_repo.delete_scheduled_summary(schedule.id)

    if success:
        click.echo(f"\n✓ Removed schedule '{schedule.name}'")
        click.echo(f"\nNote: Restart the daemon to apply changes:")
        click.echo(f"  docker-compose restart")
    else:
        click.echo(f"✗ Failed to remove schedule")
        exit(1)


@schedule_summary.command(name='enable')
@click.option('--id', 'schedule_id', type=int, help='Schedule ID to enable')
@click.option('--name', help='Schedule name to enable')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
def enable_schedule(schedule_id, name, db_path):
    """Enable a scheduled summary."""
    db_repo = DatabaseRepository(db_path)

    if not schedule_id and not name:
        click.echo("✗ Must specify --id or --name")
        exit(1)

    # Find the schedule
    if schedule_id:
        schedule = db_repo.get_scheduled_summary_by_id(schedule_id)
    else:
        schedule = db_repo.get_scheduled_summary_by_name(name)

    if not schedule:
        click.echo(f"✗ Schedule not found")
        exit(1)

    # Enable it
    db_repo.update_scheduled_summary(schedule.id, enabled=True)
    click.echo(f"\n✓ Enabled schedule '{schedule.name}'")
    click.echo(f"\nNote: Restart the daemon to apply changes:")
    click.echo(f"  docker-compose restart")


@schedule_summary.command(name='disable')
@click.option('--id', 'schedule_id', type=int, help='Schedule ID to disable')
@click.option('--name', help='Schedule name to disable')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
def disable_schedule(schedule_id, name, db_path):
    """Disable a scheduled summary."""
    db_repo = DatabaseRepository(db_path)

    if not schedule_id and not name:
        click.echo("✗ Must specify --id or --name")
        exit(1)

    # Find the schedule
    if schedule_id:
        schedule = db_repo.get_scheduled_summary_by_id(schedule_id)
    else:
        schedule = db_repo.get_scheduled_summary_by_name(name)

    if not schedule:
        click.echo(f"✗ Schedule not found")
        exit(1)

    # Disable it
    db_repo.update_scheduled_summary(schedule.id, enabled=False)
    click.echo(f"\n✓ Disabled schedule '{schedule.name}'")
    click.echo(f"\nNote: Restart the daemon to apply changes:")
    click.echo(f"  docker-compose restart")


@schedule_summary.command(name='run-now')
@click.option('--id', 'schedule_id', type=int, help='Schedule ID to run')
@click.option('--name', help='Schedule name to run')
@click.option('--dry-run', is_flag=True, help='Print summary to console instead of posting to Signal')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
@click.option('--phone', envvar='SIGNAL_PHONE_NUMBER', required=True, help='Phone number')
@click.option('--config-dir', envvar='SIGNAL_CLI_CONFIG_DIR', default='/signal-cli-config', help='Signal-CLI config directory')
@click.option('--ollama-host', envvar='OLLAMA_HOST', default='http://localhost:11434', help='Ollama host URL')
@click.option('--ollama-model', envvar='OLLAMA_MODEL', default='mistral-nemo', help='Ollama model name')
def run_now(schedule_id, name, dry_run, db_path, phone, config_dir, ollama_host, ollama_model):
    """Manually run a scheduled summary immediately."""
    from ..exporter.summary_poster import SummaryPoster
    from ..exporter.message_exporter import MessageCollector

    try:
        db_repo = DatabaseRepository(db_path)

        if not schedule_id and not name:
            click.echo("✗ Must specify --id or --name")
            exit(1)

        # Find the schedule
        if schedule_id:
            schedule = db_repo.get_scheduled_summary_by_id(schedule_id)
        else:
            schedule = db_repo.get_scheduled_summary_by_name(name)

        if not schedule:
            click.echo(f"✗ Schedule not found")
            exit(1)

        if dry_run:
            click.echo(f"\n[DRY RUN] Running schedule '{schedule.name}' manually (console output only)...")
        else:
            click.echo(f"\nRunning schedule '{schedule.name}' manually...")

        # Initialize components
        signal_cli = SignalCLI(phone, config_dir)
        message_collector = MessageCollector(signal_cli, db_repo)
        ollama = OllamaClient(ollama_host, ollama_model)
        summarizer = ChatSummarizer(ollama)
        poster = SummaryPoster(signal_cli, summarizer, db_repo, message_collector)

        # First, collect any new messages from Signal
        click.echo("Collecting messages from Signal...")
        total_received, new_stored = message_collector.receive_and_store_messages(timeout=30)
        click.echo(f"  Received {total_received} messages, {new_stored} new stored")

        # Run the summary (works for both daily and weekly schedules)
        success = poster.generate_and_post_summary(
            schedule_id=schedule.id,
            scheduled_time="manual",
            dry_run=dry_run
        )

        if success:
            if dry_run:
                click.echo(f"\n✓ Successfully generated summary for schedule '{schedule.name}' (dry run)")
            else:
                click.echo(f"\n✓ Successfully ran schedule '{schedule.name}'")
        else:
            click.echo(f"\n✗ Failed to run schedule '{schedule.name}'")
            exit(1)

    except Exception as e:
        click.echo(f"✗ Error running schedule: {e}")
        logger.error(f"Error running schedule: {e}", exc_info=True)
        exit(1)


@cli.command()
@click.option('--host', envvar='API_HOST', default='0.0.0.0', help='API server host')
@click.option('--port', envvar='API_PORT', default=8000, type=int, help='API server port')
@click.option('--reload', 'auto_reload', is_flag=True, help='Enable auto-reload for development')
def api(host, port, auto_reload):
    """Start the REST API server.

    Provides endpoints for managing schedules, viewing stats, and
    controlling the summarizer via HTTP API.

    The API requires the API_SECRET environment variable for authentication.
    """
    import os

    try:
        import uvicorn
    except ImportError:
        click.echo("✗ uvicorn is not installed. Install with: pip install uvicorn")
        exit(1)

    api_secret = os.getenv('API_SECRET')
    if not api_secret:
        click.echo("⚠️  Warning: API_SECRET not set. API authentication will be disabled!")
        click.echo("   Set API_SECRET environment variable for production use.\n")

    click.echo(f"\n=== Privacy Summarizer API ===")
    click.echo(f"Starting API server on {host}:{port}")
    click.echo(f"Documentation available at: http://{host}:{port}/api/docs")
    click.echo()

    uvicorn.run(
        "src.api.main:app",
        host=host,
        port=port,
        reload=auto_reload,
        log_level=os.getenv('LOG_LEVEL', 'info').lower()
    )


# =========================================================================
# DM Chat Management Commands
# =========================================================================

@cli.group()
def dm():
    """Manage DM chat feature."""
    pass


@dm.command(name='status')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
def dm_status(db_path):
    """Show DM chat feature status and statistics."""
    import os

    db_repo = DatabaseRepository(db_path)

    # Get DM status
    dm_enabled = os.getenv("DM_CHAT_ENABLED", "true").lower() in ("true", "1", "yes")
    dm_retention = int(os.getenv("DM_RETENTION_HOURS", "48"))

    # Get statistics
    stats = db_repo.get_dm_stats()

    click.echo("\n=== DM Chat Status ===\n")
    click.echo(f"Feature Enabled: {'✓ Yes' if dm_enabled else '✗ No'}")
    click.echo(f"Retention Period: {dm_retention} hours")
    click.echo(f"\nStatistics:")
    click.echo(f"  Total Messages: {stats['total_messages']}")
    click.echo(f"  Unique Users: {stats['unique_users']}")

    if stats['oldest_message']:
        click.echo(f"  Oldest Message: {stats['oldest_message']}")
    if stats['newest_message']:
        click.echo(f"  Newest Message: {stats['newest_message']}")

    click.echo()


@dm.command(name='enable')
def dm_enable():
    """Enable DM chat feature.

    Note: This sets the environment variable for the current process.
    For persistent changes, update DM_CHAT_ENABLED in your .env file.
    """
    import os
    os.environ["DM_CHAT_ENABLED"] = "true"
    click.echo("✓ DM chat feature enabled (for this session)")
    click.echo("  To make this permanent, set DM_CHAT_ENABLED=true in your .env file")


@dm.command(name='disable')
def dm_disable():
    """Disable DM chat feature (kill switch).

    When disabled, DMs are still received and stored, but the bot
    won't respond with AI-generated content. Commands still work.

    Note: This sets the environment variable for the current process.
    For persistent changes, update DM_CHAT_ENABLED in your .env file.
    """
    import os
    os.environ["DM_CHAT_ENABLED"] = "false"
    click.echo("✓ DM chat feature disabled (for this session)")
    click.echo("  Messages will still be stored but AI responses are paused")
    click.echo("  To make this permanent, set DM_CHAT_ENABLED=false in your .env file")


@dm.command(name='purge')
@click.option('--db-path', envvar='DB_PATH', default='/data/privacy_summarizer.db', help='Database path')
@click.option('--phone', help='Purge messages for specific phone number only')
@click.option('--all', 'purge_all', is_flag=True, help='Purge ALL DM messages (requires confirmation)')
@click.confirmation_option(prompt='Are you sure you want to purge DM messages?')
def dm_purge(db_path, phone, purge_all):
    """Purge DM conversation messages.

    By default, purges messages older than the retention period.
    Use --phone to purge a specific user's conversation.
    Use --all to purge ALL DM messages (dangerous!).
    """
    from datetime import datetime, timedelta
    import os

    db_repo = DatabaseRepository(db_path)

    if phone:
        # Purge specific phone number
        count = db_repo.purge_dm_messages(phone)
        click.echo(f"✓ Purged {count} messages for {phone}")

    elif purge_all:
        # Purge all - need to do it differently since there's no purge_all_dm_messages
        stats = db_repo.get_dm_stats()
        # Purge with far-future date to get everything
        count = db_repo.purge_expired_dm_messages(before=datetime.utcnow() + timedelta(hours=1))
        click.echo(f"✓ Purged {count} DM messages from {stats['unique_users']} users")

    else:
        # Purge expired based on retention
        retention_hours = int(os.getenv("DM_RETENTION_HOURS", "48"))
        cutoff = datetime.utcnow() - timedelta(hours=retention_hours)
        count = db_repo.purge_expired_dm_messages(before=cutoff)
        click.echo(f"✓ Purged {count} DM messages older than {retention_hours} hours")


if __name__ == '__main__':
    cli()
