"""Auto-update functionality for iuselinux."""

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

from . import __version__
from .config import get_config_value

logger = logging.getLogger("iuselinux.updater")

PYPI_URL = "https://pypi.org/pypi/iuselinux/json"
PACKAGE_NAME = "iuselinux"

# Cache update check results
_update_cache: dict[str, Any] = {}
_last_check: float = 0


def fetch_pypi_version(timeout: int = 10) -> str | None:
    """Fetch the latest version from PyPI."""
    try:
        req = Request(PYPI_URL, headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode())
            version: str | None = data.get("info", {}).get("version")
            return version
    except (URLError, json.JSONDecodeError, TimeoutError, OSError) as e:
        logger.warning("Failed to fetch PyPI version: %s", e)
        return None


def compare_versions(current: str, latest: str) -> bool:
    """Return True if latest is newer than current."""
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        return False


def get_update_status(force_check: bool = False) -> dict[str, Any]:
    """Get current update status, optionally forcing a fresh check."""
    global _update_cache, _last_check

    check_interval: int = get_config_value("update_check_interval")
    now = time.time()

    # Return cached result if recent enough
    if not force_check and _update_cache and (now - _last_check) < check_interval:
        return _update_cache

    latest = fetch_pypi_version()
    update_available = False

    if latest:
        update_available = compare_versions(__version__, latest)

    _update_cache = {
        "current_version": __version__,
        "latest_version": latest,
        "update_available": update_available,
        "last_check": datetime.now(timezone.utc).isoformat(),
        "error": None if latest else "Failed to check for updates",
    }
    _last_check = now

    return _update_cache


def find_uv_executable() -> str | None:
    """Find the uv executable."""
    return shutil.which("uv")


def perform_update() -> tuple[bool, str]:
    """Perform the package update using uv tool upgrade.

    Returns:
        Tuple of (success, message)
    """
    uv_path = find_uv_executable()
    if not uv_path:
        return False, "uv not found. Cannot perform update."

    try:
        result = subprocess.run(
            [uv_path, "tool", "upgrade", PACKAGE_NAME],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            return False, f"Update failed: {error_msg}"

        return True, "Update installed successfully. Restart required."
    except subprocess.TimeoutExpired:
        return False, "Update timed out"
    except Exception as e:
        return False, f"Update failed: {e}"


def schedule_restart(delay_seconds: float = 2.0) -> None:
    """Schedule a server restart after a delay."""
    from .service import SERVICE_LABEL, is_loaded

    def do_restart() -> None:
        time.sleep(delay_seconds)

        if is_loaded():
            # Running as LaunchAgent - use launchctl to restart
            uid = os.getuid()
            subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{uid}/{SERVICE_LABEL}"],
                capture_output=True,
            )
        else:
            # Running directly - use os.execv to restart
            os.execv(sys.executable, [sys.executable] + sys.argv)

    thread = threading.Thread(target=do_restart, daemon=True)
    thread.start()
