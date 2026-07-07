import sys

from loguru import logger

from app.config.settings import settings

# Determine log level based on environment
LOG_LEVEL = "DEBUG" if settings.env == "development" else "INFO"

# Remove default handler
logger.remove()

# Add console transport (matches Winston consoleTransport)
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> [<level>{level}</level>]: <level>{message}</level>",
    colorize=True,
    level=LOG_LEVEL,
)

# Add file transport (matches Winston fileTransport)
logger.add(
    "application.log",
    format="{time:DD-MM-YYYY HH:mm:ss} [{level}]: {message}",
    rotation="10 MB",  # Automatically rotates log files when they reach 10MB
    retention="10 days",  # Keep logs for 10 days
    level=LOG_LEVEL,
)
