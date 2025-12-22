"""iUseLinux - Read and send iMessages via local API."""

import importlib.metadata
import logging
import sys
import warnings

# Check platform immediately on import
if sys.platform != "darwin":
    _RED = "\033[91m"
    _BOLD = "\033[1m"
    _RESET = "\033[0m"

    _error_msg = f"""
{_RED}{_BOLD}ERROR: iuselinux is only supported on macOS{_RESET}

Install it on your macOS machine, then connect to it over http.
"""
    print(_error_msg, file=sys.stderr)
    raise SystemExit(1)

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
