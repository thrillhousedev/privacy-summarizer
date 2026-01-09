"""Main entry point for Privacy Summarizer."""

import os
import sys
import logging
from pathlib import Path

import colorlog


def setup_logging():
    """Set up colored logging."""
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

    # Create a colored formatter
    formatter = colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s - %(name)s - %(levelname)s%(reset)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )

    # Set up root logger
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level))

    # Suppress noisy libraries
    logging.getLogger('apscheduler').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def main():
    """Main entry point."""
    setup_logging()

    # Import CLI after logging is set up
    from .cli.commands import cli

    # Run CLI
    cli()


if __name__ == '__main__':
    main()
