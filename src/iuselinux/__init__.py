"""iUseLinux - Read and send iMessages via local API."""

import importlib.metadata
import logging
import sys

from .config import get_config_value

# Version from pyproject.toml - single source of truth
try:
    __version__ = importlib.metadata.version("iuselinux")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0+dev"  # Fallback for editable installs


def setup_logging() -> None:
    """Configure logging based on config setting."""
    level_str = get_config_value("log_level")
    level = getattr(logging, level_str.upper(), logging.WARNING)

    # Configure root logger for iuselinux
    logger = logging.getLogger("iuselinux")
    logger.setLevel(level)

    # Only add handler if not already configured
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)


# Initialize logging on import
setup_logging()
