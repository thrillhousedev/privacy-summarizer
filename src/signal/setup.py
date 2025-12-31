"""Interactive setup wizard for Signal-CLI registration."""

import logging
from typing import Optional

from .cli_wrapper import SignalCLI, SignalCLIException

logger = logging.getLogger(__name__)


class SetupWizard:
    """Interactive setup wizard for configuring Signal-CLI."""

    def __init__(self, phone_number: str, config_dir: str = "/signal-cli-config"):
        """Initialize setup wizard.

        Args:
            phone_number: Phone number to register (format: +1234567890)
            config_dir: Directory for signal-cli configuration
        """
        self.phone_number = phone_number
        self.config_dir = config_dir
        self.signal_cli = SignalCLI(phone_number, config_dir)

    def check_registration(self) -> bool:
        """Check if phone number is already registered.

        Returns:
            True if registered, False otherwise
        """
        return self.signal_cli.is_registered()

    def run_setup(self, use_voice: bool = False) -> bool:
        """Run the interactive setup process.

        Args:
            use_voice: Use voice call instead of SMS

        Returns:
            True if setup successful, False otherwise
        """
        print("\n" + "="*60)
        print("Signal-CLI Setup Wizard")
        print("="*60)
        print(f"\nPhone Number: {self.phone_number}")
        print(f"Config Directory: {self.config_dir}\n")

        # Check if already registered
        if self.check_registration():
            print("✓ Phone number is already registered with Signal!")
            print("  You can skip the registration process.\n")
            return True

        print("This phone number is not yet registered with Signal.")
        print("Starting registration process...\n")

        # Start registration
        try:
            # Prompt for CAPTCHA
            print("Signal requires a CAPTCHA for registration.")
            print("1. Visit: https://signalcaptchas.org/registration/generate.html")
            print("2. Solve the CAPTCHA")
            print("3. Right-click 'Open Signal' and copy the link")
            print("4. Paste the link below\n")

            captcha_link = input("Paste the Signal CAPTCHA link here: ").strip()

            # Extract captcha token from the link
            # Format: signalcaptcha://signal-hcaptcha.XXXXX
            captcha_token = None
            if "signal-hcaptcha." in captcha_link or "signalcaptcha://" in captcha_link:
                captcha_token = captcha_link.split("signalcaptcha://")[1] if "signalcaptcha://" in captcha_link else captcha_link
                print(f"\n✓ CAPTCHA token extracted\n")
            else:
                print("\n⚠ Could not extract CAPTCHA token, will try anyway...\n")
                captcha_token = captcha_link

            method = "voice call" if use_voice else "SMS"
            print(f"Requesting verification code via {method}...")
            result = self.signal_cli.register(use_voice=use_voice, captcha=captcha_token)
            print(f"✓ Verification code sent!\n")

            # Prompt for verification code
            print("Please check your phone for the verification code.")
            verification_code = input("Enter the 6-digit verification code: ").strip()

            if not verification_code or len(verification_code) != 6:
                print("✗ Invalid verification code format")
                return False

            # Verify the code
            print("\nVerifying code...")
            self.signal_cli.verify(verification_code)
            print("✓ Phone number verified successfully!")

            # List groups to test
            print("\nFetching your Signal groups...")
            groups = self.signal_cli.list_groups()

            if groups:
                print(f"\n✓ Found {len(groups)} group(s):")
                for i, group in enumerate(groups, 1):
                    print(f"  {i}. {group.get('name', 'Unknown')} ({group.get('id', 'N/A')})")
            else:
                print("\n! No groups found. Make sure you're a member of at least one group.")

            print("\n" + "="*60)
            print("Setup completed successfully!")
            print("="*60 + "\n")

            return True

        except SignalCLIException as e:
            print(f"\n✗ Setup failed: {e}")
            logger.error(f"Setup failed: {e}")
            return False
        except KeyboardInterrupt:
            print("\n\nSetup cancelled by user.")
            return False
        except Exception as e:
            print(f"\n✗ Unexpected error during setup: {e}")
            logger.error(f"Unexpected error during setup: {e}")
            return False

    def quick_check(self) -> dict:
        """Quick check of Signal-CLI setup status.

        Returns:
            Dictionary with status information
        """
        status = {
            "registered": False,
            "groups_count": 0,
            "groups": []
        }

        try:
            status["registered"] = self.check_registration()

            if status["registered"]:
                groups = self.signal_cli.list_groups()
                status["groups_count"] = len(groups)
                status["groups"] = groups

        except Exception as e:
            logger.error(f"Error checking status: {e}")
            status["error"] = str(e)

        return status

    def display_status(self):
        """Display current setup status."""
        print("\n" + "="*60)
        print("Signal-CLI Status")
        print("="*60)

        status = self.quick_check()

        print(f"\nPhone Number: {self.phone_number}")
        print(f"Config Directory: {self.config_dir}")

        if status.get("error"):
            print(f"\n✗ Error: {status['error']}")
        elif status["registered"]:
            print("\n✓ Registered: Yes")
            print(f"✓ Groups: {status['groups_count']}")

            if status["groups"]:
                print("\nAvailable Groups:")
                for i, group in enumerate(status["groups"], 1):
                    name = group.get("name", "Unknown")
                    group_id = group.get("id", "N/A")[:20] + "..."
                    print(f"  {i}. {name} ({group_id})")
        else:
            print("\n✗ Registered: No")
            print("  Run setup to register this phone number.")

        print("\n" + "="*60 + "\n")
