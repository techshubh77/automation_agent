import sys

from loguru import logger

# Remove default handler
logger.remove()

# Add console transport (matches Winston consoleTransport)
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> [<level>{level}</level>]: <level>{message}</level>",
    colorize=True,
    level="INFO",
)

# Add file transport (matches Winston fileTransport)
logger.add(
    "application.log",
    format="{time:DD-MM-YYYY HH:mm:ss} [{level}]: {message}",
    rotation="10 MB",  # Automatically rotates log files when they reach 10MB
    retention="10 days",  # Keep logs for 10 days
    level="INFO",
)
