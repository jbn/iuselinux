"""macOS LaunchAgent service management for iuselinux."""

import fcntl
import os
import plistlib
import shutil
import socket
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from .config import update_config


# Service constants
SERVICE_LABEL = "com.iuselinux.server"
PLIST_FILENAME = f"{SERVICE_LABEL}.plist"
DEFAULT_PORT = 1960
DEFAULT_HOST = "127.0.0.1"

# Tray service constants
TRAY_SERVICE_LABEL = "com.iuselinux.tray"
TRAY_PLIST_FILENAME = f"{TRAY_SERVICE_LABEL}.plist"

# App bundle constants (for Full Disk Access)
APP_BUNDLE_NAME = "iUseLinux Service.app"
APP_BUNDLE_IDENTIFIER = "com.iuselinux.launcher"
APP_BUNDLE_EXECUTABLE = "iuselinux-launcher"

# Tray app bundle constants (for Spotlight/Launchpad visibility)
TRAY_APP_BUNDLE_NAME = "iUseLinux.app"
TRAY_APP_BUNDLE_IDENTIFIER = "com.iuselinux.tray"
TRAY_APP_BUNDLE_EXECUTABLE = "iuselinux-tray"

# State directory for locks and PID files
STATE_DIR = Path.home() / ".local" / "state" / "iuselinux"


@contextmanager
def _service_lock() -> Generator[None, None, None]:
    """Acquire exclusive lock for install/uninstall operations.

    Prevents race conditions when multiple processes attempt to install
    or uninstall the service concurrently. The lock is automatically
    released when the process exits or crashes.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = STATE_DIR / "service.lock"
    with open(lock_file, "w") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


def get_launch_agents_dir() -> Path:
    """Get the LaunchAgents directory path."""
    return Path.home() / "Library" / "LaunchAgents"


def get_plist_path() -> Path:
    """Get the full path to the plist file."""
    return get_launch_agents_dir() / PLIST_FILENAME


def get_log_paths() -> tuple[Path, Path]:
    """Get paths for stdout and stderr logs."""
    log_dir = Path.home() / "Library" / "Logs" / "iuselinux"
    return log_dir / "iuselinux.log", log_dir / "iuselinux.err"


def get_app_support_dir() -> Path:
    """Get the Application Support directory for iuselinux."""
    return Path.home() / "Library" / "Application Support" / "iuselinux"


def get_app_bundle_path() -> Path:
    """Get the path to the app bundle used for Full Disk Access."""
    return get_app_support_dir() / APP_BUNDLE_NAME


def get_app_icon_path() -> Path:
    """Get the path to the app icon file."""
    return Path(__file__).parent / "static" / "AppIcon.icns"


def create_app_bundle() -> Path:
    """Create minimal app bundle for Full Disk Access permissions.

    When running as a LaunchAgent service, users need to grant Full Disk Access
    to an app bundle rather than a terminal. This creates a minimal .app that
    wraps the iuselinux launcher script.

    Returns:
        Path to the created .app bundle

    Raises:
        BundleOwnershipError: If an existing app at the target path is not ours
    """
    app_path = get_app_bundle_path()

    # Verify ownership before overwriting - prevent destroying user's apps
    verify_bundle_ownership(app_path, APP_BUNDLE_IDENTIFIER)

    contents_path = app_path / "Contents"
    macos_path = contents_path / "MacOS"
    resources_path = contents_path / "Resources"

    # Create directory structure
    macos_path.mkdir(parents=True, exist_ok=True)
    resources_path.mkdir(parents=True, exist_ok=True)

    # Copy app icon if available
    icon_src = get_app_icon_path()
    if icon_src.exists():
        shutil.copy2(icon_src, resources_path / "AppIcon.icns")

    # Create Info.plist
    info_plist = {
        "CFBundleExecutable": APP_BUNDLE_EXECUTABLE,
        "CFBundleIdentifier": APP_BUNDLE_IDENTIFIER,
        "CFBundleName": "iUseLinux Service",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundleIconFile": "AppIcon",
    }

    plist_path = contents_path / "Info.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(info_plist, f)

    # Create the launcher shell script
    # This script detects the best way to run iuselinux at runtime
    launcher_script = """\
#!/bin/bash
# iUseLinux service launcher - add this app to Full Disk Access
# Location: ~/Library/Application Support/iuselinux/iUseLinux Service.app

# Include common paths where uv/uvx/pyenv might be installed
export PATH="$HOME/.local/bin:$HOME/.pyenv/shims:/opt/homebrew/bin:/usr/local/bin:$PATH"

if command -v uvx &> /dev/null; then
    exec uvx iuselinux "$@"
elif command -v iuselinux &> /dev/null; then
    exec iuselinux "$@"
else
    exec python3 -m iuselinux "$@"
fi
"""

    exec_path = macos_path / APP_BUNDLE_EXECUTABLE
    with open(exec_path, "w") as f:
        f.write(launcher_script)

    # Make executable (755 permissions)
    st = os.stat(exec_path)
    os.chmod(exec_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return app_path


def remove_app_bundle() -> None:
    """Remove the app bundle if it exists.

    Raises:
        BundleOwnershipError: If the existing app is not ours
    """
    app_path = get_app_bundle_path()
    if app_path.exists():
        # Verify ownership before deletion - prevent destroying user's apps
        verify_bundle_ownership(app_path, APP_BUNDLE_IDENTIFIER)
        shutil.rmtree(app_path)


def get_launcher_executable() -> str:
    """Get the path to the launcher executable inside the app bundle."""
    return str(get_app_bundle_path() / "Contents" / "MacOS" / APP_BUNDLE_EXECUTABLE)


def get_user_applications_dir() -> Path:
    """Get the user's Applications directory."""
    return Path.home() / "Applications"


def get_tray_app_bundle_path() -> Path:
    """Get the path to the tray app bundle in ~/Applications."""
    return get_user_applications_dir() / TRAY_APP_BUNDLE_NAME


class BundleOwnershipError(Exception):
    """Raised when an existing app bundle is not owned by iUseLinux."""

    pass


def verify_bundle_ownership(app_path: Path, expected_identifier: str) -> bool:
    """Verify that an existing app bundle belongs to iUseLinux.

    Args:
        app_path: Path to the .app bundle
        expected_identifier: The CFBundleIdentifier we expect (e.g. "com.iuselinux.tray")

    Returns:
        True if the bundle is ours or doesn't exist, False if it exists but belongs to someone else

    Raises:
        BundleOwnershipError: If the bundle exists but has a different identifier
    """
    if not app_path.exists():
        return True

    info_plist = app_path / "Contents" / "Info.plist"
    if not info_plist.exists():
        # Malformed bundle without Info.plist - refuse to overwrite
        raise BundleOwnershipError(
            f"Existing app at {app_path} has no Info.plist - refusing to overwrite"
        )

    try:
        with open(info_plist, "rb") as f:
            plist = plistlib.load(f)
        actual_identifier = plist.get("CFBundleIdentifier", "")
        if actual_identifier != expected_identifier:
            raise BundleOwnershipError(
                f"Existing app at {app_path} has identifier '{actual_identifier}', "
                f"expected '{expected_identifier}' - refusing to overwrite"
            )
        return True
    except plistlib.InvalidFileException as e:
        raise BundleOwnershipError(
            f"Existing app at {app_path} has invalid Info.plist: {e}"
        )


def create_tray_app_bundle() -> Path:
    """Create tray app bundle in ~/Applications for Spotlight/Launchpad visibility.

    This creates a proper .app that users can find in Spotlight, add to Dock,
    and launch manually if the tray was quit.

    Returns:
        Path to the created .app bundle

    Raises:
        BundleOwnershipError: If an existing app at the target path is not ours
    """
    app_path = get_tray_app_bundle_path()

    # Verify ownership before overwriting - prevent destroying user's apps
    verify_bundle_ownership(app_path, TRAY_APP_BUNDLE_IDENTIFIER)

    contents_path = app_path / "Contents"
    macos_path = contents_path / "MacOS"
    resources_path = contents_path / "Resources"

    # Ensure ~/Applications exists
    get_user_applications_dir().mkdir(parents=True, exist_ok=True)

    # Create directory structure
    macos_path.mkdir(parents=True, exist_ok=True)
    resources_path.mkdir(parents=True, exist_ok=True)

    # Copy app icon if available
    icon_src = get_app_icon_path()
    if icon_src.exists():
        shutil.copy2(icon_src, resources_path / "AppIcon.icns")

    # Create Info.plist
    info_plist = {
        "CFBundleExecutable": TRAY_APP_BUNDLE_EXECUTABLE,
        "CFBundleIdentifier": TRAY_APP_BUNDLE_IDENTIFIER,
        "CFBundleName": "iUseLinux",
        "CFBundleDisplayName": "iUseLinux",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundleIconFile": "AppIcon",
        "LSUIElement": True,  # Makes it a menu bar app (no Dock icon when running)
    }

    plist_path = contents_path / "Info.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(info_plist, f)

    # Create the launcher shell script
    launcher_script = """\
#!/bin/bash
# iUseLinux - menu bar tray icon
# Launch this app to show the iUseLinux menu bar icon

# Include common paths where uv/uvx/pyenv might be installed
export PATH="$HOME/.local/bin:$HOME/.pyenv/shims:/opt/homebrew/bin:/usr/local/bin:$PATH"

if command -v uvx &> /dev/null; then
    exec uvx iuselinux tray run
elif command -v iuselinux &> /dev/null; then
    exec iuselinux tray run
else
    exec python3 -m iuselinux tray run
fi
"""

    exec_path = macos_path / TRAY_APP_BUNDLE_EXECUTABLE
    with open(exec_path, "w") as f:
        f.write(launcher_script)

    # Make executable (755 permissions)
    st = os.stat(exec_path)
    os.chmod(exec_path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return app_path


def remove_tray_app_bundle() -> None:
    """Remove the tray app bundle if it exists.

    Raises:
        BundleOwnershipError: If the existing app is not ours
    """
    app_path = get_tray_app_bundle_path()
    if app_path.exists():
        # Verify ownership before deletion - prevent destroying user's apps
        verify_bundle_ownership(app_path, TRAY_APP_BUNDLE_IDENTIFIER)
        shutil.rmtree(app_path)


def get_tray_launcher_executable() -> str:
    """Get the path to the tray launcher executable inside the app bundle."""
    return str(get_tray_app_bundle_path() / "Contents" / "MacOS" / TRAY_APP_BUNDLE_EXECUTABLE)


def find_iuselinux_executable() -> str | None:
    """Find the iuselinux executable path.

    Tries multiple approaches:
    1. Use 'which iuselinux' to find it in PATH
    2. Look for uvx and construct a uvx command
    3. Fall back to current Python's entry point
    """
    # Try to find iuselinux directly
    result = subprocess.run(
        ["which", "iuselinux"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()

    # Try to find uvx
    uvx_path = shutil.which("uvx")
    if uvx_path:
        # Return a marker that we should use uvx
        return f"uvx:iuselinux"

    # Fall back to Python module execution
    return f"python:{sys.executable}"


def generate_plist(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> dict:
    """Generate the launchd plist dictionary.

    Uses the app bundle launcher script, which allows users to grant
    Full Disk Access to the iUseLinux.app rather than needing to find
    the underlying python3 or uvx binary.
    """
    stdout_log, stderr_log = get_log_paths()

    # Ensure log directory exists
    stdout_log.parent.mkdir(parents=True, exist_ok=True)

    # Use the app bundle launcher - this allows users to grant FDA to the .app
    program_args = [
        get_launcher_executable(),
        "--host", host,
        "--port", str(port),
    ]

    return {
        "Label": SERVICE_LABEL,
        "ProgramArguments": program_args,
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(stdout_log),
        "StandardErrorPath": str(stderr_log),
        "EnvironmentVariables": {
            # Ensure we have a proper PATH for finding ffmpeg, tailscale, etc.
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            # Mark that we're running as the launchd service (for conflict detection)
            "IUSELINUX_LAUNCHD_SERVICE": "1",
        },
    }


def is_installed() -> bool:
    """Check if the LaunchAgent plist is installed."""
    return get_plist_path().exists()


def is_loaded() -> bool:
    """Check if the service is loaded in launchd."""
    result = subprocess.run(
        ["launchctl", "list", SERVICE_LABEL],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def get_pid() -> int | None:
    """Get the PID of the running service, if any."""
    # Use launchctl list (no argument) which outputs tabular format:
    # PID\tStatus\tLabel  (or "-" for PID if not running)
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    # Find our service in the output
    for line in result.stdout.strip().split("\n"):
        if SERVICE_LABEL in line:
            parts = line.split("\t")
            if len(parts) >= 1:
                try:
                    return int(parts[0])
                except ValueError:
                    return None  # "-" means not running
    return None


def install(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    force: bool = False,
    tray: bool = True,
) -> tuple[bool, str]:
    """Install the LaunchAgent.

    Args:
        host: Host to bind to
        port: Port to bind to
        force: Overwrite existing installation
        tray: Also install the menu bar tray icon

    Returns:
        Tuple of (success, message)
    """
    with _service_lock():
        plist_path = get_plist_path()

        if plist_path.exists() and not force:
            return False, f"Service already installed at {plist_path}. Use --force to overwrite."

        # Create the app bundle for Full Disk Access
        # This must be done before generating the plist since plist references it
        app_bundle_path = create_app_bundle()

        # Ensure LaunchAgents directory exists
        plist_path.parent.mkdir(parents=True, exist_ok=True)

        # Unload existing service if loaded
        if is_loaded():
            unload_result = subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
                text=True,
            )
            if unload_result.returncode != 0:
                # If unload fails, the subsequent load will likely fail too
                return False, f"Failed to unload existing service: {unload_result.stderr}"

        # Generate and write plist
        plist_data = generate_plist(host=host, port=port)
        with open(plist_path, "wb") as f:
            plistlib.dump(plist_data, f)

        # Load the service
        result = subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return False, f"Failed to load service: {result.stderr}"

        messages = [
            "Service installed and started.",
            f"For Full Disk Access, add: {app_bundle_path}",
            "Logs at ~/Library/Logs/iuselinux/",
        ]

        # Install tray if requested
        if tray:
            tray_success, tray_msg = install_tray(force=force)
            if tray_success:
                messages.append("Menu bar tray icon installed.")
            else:
                messages.append(f"Warning: Tray installation failed: {tray_msg}")

        return True, " ".join(messages)


def uninstall() -> tuple[bool, str]:
    """Uninstall the LaunchAgent.

    Also uninstalls the tray LaunchAgent if installed, disables Tailscale
    serve if it was enabled, clears the Tailscale config, and removes
    the app bundle.

    Uses best-effort cleanup: continues removing components even if some
    steps fail, collecting warnings rather than failing early.

    Returns:
        Tuple of (success, message)
    """
    with _service_lock():
        plist_path = get_plist_path()

        if not plist_path.exists():
            return False, "Service is not installed."

        messages = []
        warnings = []

        # Unload the service if loaded (best-effort - continue cleanup even if this fails)
        if is_loaded():
            result = subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                warnings.append(f"launchctl unload failed: {result.stderr.strip()}")

        # Remove the plist file
        try:
            plist_path.unlink()
            messages.append("Service uninstalled.")
        except OSError as e:
            warnings.append(f"Failed to remove plist: {e}")

        # Remove the app bundle used for Full Disk Access
        remove_app_bundle()

        # Uninstall tray if installed
        if is_tray_installed():
            tray_success, tray_msg = uninstall_tray()
            if tray_success:
                messages.append("Menu bar tray icon uninstalled.")
            else:
                warnings.append(f"Tray uninstall failed: {tray_msg}")

        # Disable Tailscale serve to avoid leaving a dangling port
        # This is a best-effort cleanup - we don't fail uninstall if this fails
        if is_tailscale_available() and is_tailscale_serving():
            disable_tailscale_serve()

        # Clear Tailscale config so it doesn't auto-enable on reinstall
        update_config({"tailscale_serve_enabled": False})

        # Build final message
        if not messages:
            messages.append("Service uninstalled.")

        if warnings:
            messages.append("Warnings: " + "; ".join(warnings))
            # Still return success since we did remove components
            # User may need to manually clean up the warned items

        return True, " ".join(messages)


def get_status() -> dict:
    """Get detailed service status.

    Returns:
        Dictionary with status information
    """
    installed = is_installed()
    loaded = is_loaded() if installed else False
    pid = get_pid() if loaded else None

    status = {
        "installed": installed,
        "loaded": loaded,
        "running": pid is not None,
        "pid": pid,
        "plist_path": str(get_plist_path()) if installed else None,
    }

    # Get log file paths and sizes
    if installed:
        stdout_log, stderr_log = get_log_paths()
        status["stdout_log"] = str(stdout_log) if stdout_log.exists() else None
        status["stderr_log"] = str(stderr_log) if stderr_log.exists() else None

    # Include Tailscale status
    status.update(get_tailscale_status())

    return status


def format_status(status: dict) -> str:
    """Format status dict for human-readable output."""
    lines = []

    if not status["installed"]:
        lines.append("Service: not installed")
        lines.append(f"  Run 'iuselinux service install' to install")
        return "\n".join(lines)

    if status["running"]:
        lines.append(f"Service: running (PID {status['pid']})")
    elif status["loaded"]:
        lines.append("Service: loaded but not running")
    else:
        lines.append("Service: installed but not loaded")

    lines.append(f"  Plist: {status['plist_path']}")

    if status.get("stdout_log"):
        lines.append(f"  Logs: {status['stdout_log']}")

    # Tailscale status
    if status.get("tailscale_available"):
        if status.get("tailscale_serving"):
            ts_url = status.get("tailscale_url")
            if ts_url:
                lines.append(f"  Tailscale: {ts_url}")
            else:
                lines.append(f"  Tailscale: serving on port {status.get('tailscale_serve_port', 'unknown')}")
        else:
            lines.append("  Tailscale: available but not serving")
    elif status.get("tailscale_available") is False:
        pass  # Don't mention if not available

    return "\n".join(lines)


# Tailscale integration

def is_tailscale_available() -> bool:
    """Check if the tailscale CLI is available."""
    return shutil.which("tailscale") is not None


def is_tailscale_connected() -> bool:
    """Check if Tailscale is connected."""
    if not is_tailscale_available():
        return False

    result = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False

    try:
        import json
        status = json.loads(result.stdout)
        # BackendState can be "Running", "Stopped", "NeedsLogin", etc.
        return status.get("BackendState") == "Running"
    except (json.JSONDecodeError, KeyError):
        return False


def get_tailscale_serve_status() -> dict | None:
    """Get current tailscale serve configuration.

    Returns:
        Dict with serve info or None if not serving
    """
    if not is_tailscale_available():
        return None

    result = subprocess.run(
        ["tailscale", "serve", "status", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    try:
        import json
        status = json.loads(result.stdout)
        # Check if there's any serve configuration
        if status and status.get("TCP") or status.get("Web"):
            return status
        return None
    except (json.JSONDecodeError, KeyError):
        return None


# Global handle for the tailscale serve subprocess
_tailscale_serve_proc: subprocess.Popen[bytes] | None = None
_atexit_registered: bool = False


def get_tailscale_pid_file() -> Path:
    """Get the path to the tailscale serve PID file.

    Uses ~/.local/state/iuselinux/ following XDG conventions for runtime state.
    """
    state_dir = Path.home() / ".local" / "state" / "iuselinux"
    return state_dir / "tailscale_serve.pid"


def _write_tailscale_pid(pid: int) -> None:
    """Write the tailscale serve subprocess PID to the PID file."""
    pid_file = get_tailscale_pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid))


def _read_tailscale_pid() -> int | None:
    """Read the tailscale serve subprocess PID from the PID file.

    Returns:
        The PID if file exists and is valid, None otherwise
    """
    pid_file = get_tailscale_pid_file()
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def _remove_tailscale_pid_file() -> None:
    """Remove the tailscale serve PID file if it exists."""
    pid_file = get_tailscale_pid_file()
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def _is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)  # Signal 0 just checks if process exists
        return True
    except OSError:
        return False


def _kill_orphan_tailscale_serve() -> bool:
    """Kill any orphan tailscale serve process from a previous run.

    Reads the PID file, checks if that process is still running,
    and terminates it if so.

    Returns:
        True if an orphan was killed, False otherwise
    """
    pid = _read_tailscale_pid()
    if pid is None:
        return False

    if not _is_process_running(pid):
        # Stale PID file, just clean it up
        _remove_tailscale_pid_file()
        return False

    # Kill the orphan process
    try:
        os.kill(pid, 15)  # SIGTERM
        # Wait briefly for it to die
        import time
        for _ in range(10):  # Wait up to 1 second
            time.sleep(0.1)
            if not _is_process_running(pid):
                break
        else:
            # Still running, force kill
            os.kill(pid, 9)  # SIGKILL
    except OSError:
        pass

    _remove_tailscale_pid_file()
    return True


def _cleanup_tailscale_serve_atexit() -> None:
    """Cleanup function called at process exit to terminate tailscale serve."""
    global _tailscale_serve_proc
    if _tailscale_serve_proc is not None:
        try:
            if _tailscale_serve_proc.poll() is None:
                _tailscale_serve_proc.terminate()
                _tailscale_serve_proc.wait(timeout=2)
        except Exception:
            try:
                _tailscale_serve_proc.kill()
            except Exception:
                pass
    _remove_tailscale_pid_file()


def is_tailscale_serving(port: int = DEFAULT_PORT) -> bool:
    """Check if tailscale is currently serving on the given port."""
    # First check if our managed subprocess is running (in-process)
    if _tailscale_serve_proc is not None and _tailscale_serve_proc.poll() is None:
        return True

    # Check PID file for cross-process detection (e.g., CLI checking service's tailscale)
    pid = _read_tailscale_pid()
    if pid is not None and _is_process_running(pid):
        return True

    # Fall back to checking daemon config (for --bg mode or external config)
    status = get_tailscale_serve_status()
    if not status:
        return False

    # Check TCP handlers
    tcp = status.get("TCP", {})
    if str(port) in tcp or port in tcp:
        return True

    # Check Web handlers (HTTP/HTTPS)
    web = status.get("Web", {})
    for listener_config in web.values():
        handlers = listener_config.get("Handlers", {})
        for handler in handlers.values():
            proxy = handler.get("Proxy", "")
            if f":{port}" in proxy or f"localhost:{port}" in proxy:
                return True

    return False


def enable_tailscale_serve(port: int = DEFAULT_PORT) -> tuple[bool, str]:
    """Enable tailscale serve for the given port.

    Starts tailscale serve as a foreground subprocess (no --bg). This ties
    the serve lifecycle to the iuselinux process - when iuselinux dies,
    the serve automatically stops because foreground mode is ephemeral.

    Additionally:
    - Kills any orphan tailscale serve from a previous crashed run
    - Writes PID to file for cross-process control (CLI can kill service's tailscale)
    - Registers atexit handler for graceful cleanup
    - Uses process group so child dies with parent even on SIGKILL

    Args:
        port: The port to serve

    Returns:
        Tuple of (success, message)
    """
    global _tailscale_serve_proc, _atexit_registered
    import atexit
    import time

    if not is_tailscale_available():
        return False, "Tailscale CLI not found. Install Tailscale from https://tailscale.com/download"

    if not is_tailscale_connected():
        return False, "Tailscale is not connected. Run 'tailscale up' to connect."

    # Kill any orphan from a previous crashed run
    _kill_orphan_tailscale_serve()

    # Terminate existing subprocess if any (in-process)
    if _tailscale_serve_proc is not None and _tailscale_serve_proc.poll() is None:
        _tailscale_serve_proc.terminate()
        try:
            _tailscale_serve_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _tailscale_serve_proc.kill()
        _remove_tailscale_pid_file()

    # Register atexit handler (only once)
    if not _atexit_registered:
        atexit.register(_cleanup_tailscale_serve_atexit)
        _atexit_registered = True

    # Start foreground serve (no --bg = ephemeral, dies with process)
    # Use start_new_session=True to create a new process group - this helps
    # ensure the subprocess is properly terminated even if parent gets SIGKILL
    try:
        _tailscale_serve_proc = subprocess.Popen(
            ["tailscale", "serve", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        # Write PID file for cross-process control
        _write_tailscale_pid(_tailscale_serve_proc.pid)

        # Brief delay to check for immediate failure
        time.sleep(0.5)
        if _tailscale_serve_proc.poll() is not None:
            stderr = _tailscale_serve_proc.stderr.read().decode() if _tailscale_serve_proc.stderr else ""
            _remove_tailscale_pid_file()
            return False, f"Failed to start tailscale serve: {stderr}"
    except Exception as e:
        _remove_tailscale_pid_file()
        return False, f"Failed to start tailscale serve: {e}"

    return True, f"Tailscale serve enabled for port {port}"


def disable_tailscale_serve() -> tuple[bool, str]:
    """Disable tailscale serve.

    Terminates the tailscale serve subprocess. Works both in-process (if we
    started it) and cross-process (CLI disabling service's tailscale) by
    reading the PID file.

    Returns:
        Tuple of (success, message)
    """
    global _tailscale_serve_proc
    killed = False

    # First try in-process termination (if we're the process that started it)
    if _tailscale_serve_proc is not None:
        if _tailscale_serve_proc.poll() is None:
            _tailscale_serve_proc.terminate()
            try:
                _tailscale_serve_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _tailscale_serve_proc.kill()
            killed = True
        _tailscale_serve_proc = None
        _remove_tailscale_pid_file()

    # Also try cross-process termination via PID file (e.g., CLI disabling service's tailscale)
    if not killed:
        pid = _read_tailscale_pid()
        if pid is not None and _is_process_running(pid):
            try:
                os.kill(pid, 15)  # SIGTERM
                # Wait briefly for it to die
                import time
                for _ in range(50):  # Wait up to 5 seconds
                    time.sleep(0.1)
                    if not _is_process_running(pid):
                        break
                else:
                    # Still running, force kill
                    os.kill(pid, 9)  # SIGKILL
                killed = True
            except OSError:
                pass
        _remove_tailscale_pid_file()

    return True, "Tailscale serve disabled"


def get_tailscale_dns_name() -> str | None:
    """Get the Tailscale DNS name for this machine.

    Returns:
        DNS name like 'machine-name.tailnet-name.ts.net' or None if unavailable
    """
    if not is_tailscale_available():
        return None

    result = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    try:
        import json
        status = json.loads(result.stdout)
        dns_name = status.get("Self", {}).get("DNSName", "")
        # DNSName ends with a trailing dot, remove it
        return dns_name.rstrip(".") if dns_name else None
    except (json.JSONDecodeError, KeyError):
        return None


def get_tailscale_url() -> str | None:
    """Get the HTTPS URL for Tailscale serve.

    Returns:
        URL like 'https://machine-name.tailnet-name.ts.net' or None
    """
    dns_name = get_tailscale_dns_name()
    if dns_name:
        return f"https://{dns_name}"
    return None


def get_tailscale_status() -> dict:
    """Get Tailscale status information.

    Returns:
        Dictionary with Tailscale status
    """
    available = is_tailscale_available()
    connected = is_tailscale_connected() if available else False
    serving = is_tailscale_serving() if connected else False

    status = {
        "tailscale_available": available,
        "tailscale_connected": connected,
        "tailscale_serving": serving,
    }

    if serving:
        status["tailscale_serve_port"] = DEFAULT_PORT

    if connected:
        dns_name = get_tailscale_dns_name()
        if dns_name:
            status["tailscale_dns_name"] = dns_name
            status["tailscale_url"] = f"https://{dns_name}"

    return status


# Port detection

def is_port_in_use(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """Check if a port is currently in use.

    Args:
        host: Host to check
        port: Port to check

    Returns:
        True if port is in use, False otherwise
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def is_running_as_launchd_service() -> bool:
    """Check if we are running as the launchd service.

    The launchd plist sets IUSELINUX_LAUNCHD_SERVICE=1 to mark service processes.
    """
    return os.environ.get("IUSELINUX_LAUNCHD_SERVICE") == "1"


def check_startup_conflicts(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> tuple[bool, str | None]:
    """Check for conflicts that would prevent starting the server.

    Args:
        host: Host to bind to
        port: Port to bind to

    Returns:
        Tuple of (can_start, message). If can_start is False, message explains why.
    """
    # Skip conflict check if we ARE the launchd service
    if is_running_as_launchd_service():
        return True, None

    # Check if the LaunchAgent service is running
    service_pid = get_pid()
    if is_loaded() and service_pid is not None:
        msg = (
            f"iuselinux service is already running (PID {service_pid}).\n"
            f"\n"
            f"The server is available at http://{host}:{port}\n"
            f"\n"
            f"To stop the service:  iuselinux service uninstall\n"
            f"To view status:       iuselinux service status"
        )
        return False, msg

    # Check if port is in use by something else
    if is_port_in_use(host, port):
        msg = (
            f"Port {port} is already in use on {host}.\n"
            f"\n"
            f"This could be another instance of iuselinux or a different application.\n"
            f"\n"
            f"To find what's using the port:\n"
            f"  lsof -i :{port}\n"
            f"\n"
            f"To use a different port:\n"
            f"  iuselinux --port 8080"
        )
        return False, msg

    return True, None


# Tray LaunchAgent management

def get_tray_plist_path() -> Path:
    """Get the full path to the tray plist file."""
    return get_launch_agents_dir() / TRAY_PLIST_FILENAME


def get_tray_log_paths() -> tuple[Path, Path]:
    """Get paths for tray stdout and stderr logs."""
    log_dir = Path.home() / "Library" / "Logs" / "iuselinux"
    return log_dir / "tray.log", log_dir / "tray.err"


def generate_tray_plist() -> dict[str, object]:
    """Generate the tray app launchd plist dictionary.

    Uses the tray app bundle from ~/Applications, which users can also
    launch manually from Spotlight/Launchpad if they quit the tray.

    Note: KeepAlive is NOT set, so the tray won't auto-restart if quit.
    This is intentional - when users click Quit, they expect it to quit.
    """
    stdout_log, stderr_log = get_tray_log_paths()

    # Ensure log directory exists
    stdout_log.parent.mkdir(parents=True, exist_ok=True)

    # Use the tray app bundle - allows users to find/launch via Spotlight
    program_args = [get_tray_launcher_executable()]

    return {
        "Label": TRAY_SERVICE_LABEL,
        "ProgramArguments": program_args,
        "RunAtLoad": True,
        # No KeepAlive - tray should stay quit when user quits it
        "StandardOutPath": str(stdout_log),
        "StandardErrorPath": str(stderr_log),
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        },
    }


def is_tray_installed() -> bool:
    """Check if the tray LaunchAgent plist is installed."""
    return get_tray_plist_path().exists()


def is_tray_loaded() -> bool:
    """Check if the tray service is loaded in launchd."""
    result = subprocess.run(
        ["launchctl", "list", TRAY_SERVICE_LABEL],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def get_tray_pid() -> int | None:
    """Get the PID of the running tray, if any."""
    # Use launchctl list (no argument) which outputs tabular format:
    # PID\tStatus\tLabel  (or "-" for PID if not running)
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    # Find our service in the output
    for line in result.stdout.strip().split("\n"):
        if TRAY_SERVICE_LABEL in line:
            parts = line.split("\t")
            if len(parts) >= 1:
                try:
                    return int(parts[0])
                except ValueError:
                    return None  # "-" means not running
    return None


def install_tray(force: bool = False) -> tuple[bool, str]:
    """Install the tray LaunchAgent.

    Creates an app bundle in ~/Applications that users can find in Spotlight,
    and a LaunchAgent that starts the tray on login.

    Returns:
        Tuple of (success, message)
    """
    plist_path = get_tray_plist_path()

    if plist_path.exists() and not force:
        return False, f"Tray already installed at {plist_path}. Use --force to overwrite."

    # Create the tray app bundle in ~/Applications
    # This must be done before generating the plist since plist references it
    tray_app_path = create_tray_app_bundle()

    # Ensure LaunchAgents directory exists
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    # Unload existing tray if loaded
    if is_tray_loaded():
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
        )

    # Generate and write plist
    plist_data = generate_tray_plist()
    with open(plist_path, "wb") as f:
        plistlib.dump(plist_data, f)

    # Load the tray
    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return False, f"Failed to load tray: {result.stderr}"

    return True, f"Tray installed at {tray_app_path} and started."


def uninstall_tray() -> tuple[bool, str]:
    """Uninstall the tray LaunchAgent and app bundle.

    Returns:
        Tuple of (success, message)
    """
    plist_path = get_tray_plist_path()

    if not plist_path.exists():
        return False, "Tray is not installed."

    # Unload the tray if loaded
    if is_tray_loaded():
        result = subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, f"Failed to unload tray: {result.stderr}"

    # Remove the plist file
    plist_path.unlink()

    # Remove the tray app bundle from ~/Applications
    remove_tray_app_bundle()

    return True, "Tray uninstalled."


def get_tray_status() -> dict[str, object]:
    """Get detailed tray status.

    Returns:
        Dictionary with status information
    """
    installed = is_tray_installed()
    loaded = is_tray_loaded() if installed else False
    pid = get_tray_pid() if loaded else None

    status: dict[str, object] = {
        "installed": installed,
        "loaded": loaded,
        "running": pid is not None,
        "pid": pid,
        "plist_path": str(get_tray_plist_path()) if installed else None,
    }

    # Get log file paths
    if installed:
        stdout_log, stderr_log = get_tray_log_paths()
        status["stdout_log"] = str(stdout_log) if stdout_log.exists() else None
        status["stderr_log"] = str(stderr_log) if stderr_log.exists() else None

    return status
