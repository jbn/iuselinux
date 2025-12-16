"""macOS LaunchAgent service management for iuselinux."""

import os
import plistlib
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

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
APP_BUNDLE_NAME = "iUseLinux.app"
APP_BUNDLE_IDENTIFIER = "com.iuselinux.launcher"
APP_BUNDLE_EXECUTABLE = "iuselinux-launcher"

# Tray app bundle constants (for Spotlight/Launchpad visibility)
TRAY_APP_BUNDLE_NAME = "iUseLinux Menu.app"
TRAY_APP_BUNDLE_IDENTIFIER = "com.iuselinux.tray"
TRAY_APP_BUNDLE_EXECUTABLE = "iuselinux-tray"


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


def create_app_bundle() -> Path:
    """Create minimal app bundle for Full Disk Access permissions.

    When running as a LaunchAgent service, users need to grant Full Disk Access
    to an app bundle rather than a terminal. This creates a minimal .app that
    wraps the iuselinux launcher script.

    Returns:
        Path to the created .app bundle
    """
    app_path = get_app_bundle_path()
    contents_path = app_path / "Contents"
    macos_path = contents_path / "MacOS"

    # Create directory structure
    macos_path.mkdir(parents=True, exist_ok=True)

    # Create Info.plist
    info_plist = {
        "CFBundleExecutable": APP_BUNDLE_EXECUTABLE,
        "CFBundleIdentifier": APP_BUNDLE_IDENTIFIER,
        "CFBundleName": "iUseLinux",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
    }

    plist_path = contents_path / "Info.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(info_plist, f)

    # Create the launcher shell script
    # This script detects the best way to run iuselinux at runtime
    launcher_script = """\
#!/bin/bash
# iUseLinux service launcher - add this app to Full Disk Access
# Location: ~/Library/Application Support/iuselinux/iUseLinux.app

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

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
    """Remove the app bundle if it exists."""
    app_path = get_app_bundle_path()
    if app_path.exists():
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


def create_tray_app_bundle() -> Path:
    """Create tray app bundle in ~/Applications for Spotlight/Launchpad visibility.

    This creates a proper .app that users can find in Spotlight, add to Dock,
    and launch manually if the tray was quit.

    Returns:
        Path to the created .app bundle
    """
    app_path = get_tray_app_bundle_path()
    contents_path = app_path / "Contents"
    macos_path = contents_path / "MacOS"

    # Ensure ~/Applications exists
    get_user_applications_dir().mkdir(parents=True, exist_ok=True)

    # Create directory structure
    macos_path.mkdir(parents=True, exist_ok=True)

    # Create Info.plist
    info_plist = {
        "CFBundleExecutable": TRAY_APP_BUNDLE_EXECUTABLE,
        "CFBundleIdentifier": TRAY_APP_BUNDLE_IDENTIFIER,
        "CFBundleName": "iUseLinux Menu",
        "CFBundleDisplayName": "iUseLinux Menu",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,  # Makes it a menu bar app (no Dock icon when running)
    }

    plist_path = contents_path / "Info.plist"
    with open(plist_path, "wb") as f:
        plistlib.dump(info_plist, f)

    # Create the launcher shell script
    launcher_script = """\
#!/bin/bash
# iUseLinux Menu - menu bar tray icon
# Launch this app to show the iUseLinux menu bar icon

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

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
    """Remove the tray app bundle if it exists."""
    app_path = get_tray_app_bundle_path()
    if app_path.exists():
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
    result = subprocess.run(
        ["launchctl", "list", SERVICE_LABEL],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    # Parse the output - format is: PID\tStatus\tLabel
    # Or: -\tStatus\tLabel if not running
    lines = result.stdout.strip().split("\n")
    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 1:
            try:
                return int(parts[0])
            except ValueError:
                return None
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
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
        )

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

    Returns:
        Tuple of (success, message)
    """
    plist_path = get_plist_path()

    if not plist_path.exists():
        return False, "Service is not installed."

    # Unload the service if loaded
    if is_loaded():
        result = subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, f"Failed to unload service: {result.stderr}"

    # Remove the plist file
    plist_path.unlink()

    messages = ["Service uninstalled."]

    # Remove the app bundle used for Full Disk Access
    remove_app_bundle()

    # Uninstall tray if installed
    if is_tray_installed():
        tray_success, tray_msg = uninstall_tray()
        if tray_success:
            messages.append("Menu bar tray icon uninstalled.")
        else:
            messages.append(f"Warning: Tray uninstall failed: {tray_msg}")

    # Disable Tailscale serve to avoid leaving a dangling port
    # This is a best-effort cleanup - we don't fail uninstall if this fails
    if is_tailscale_available() and is_tailscale_serving():
        disable_tailscale_serve()

    # Clear Tailscale config so it doesn't auto-enable on reinstall
    update_config({"tailscale_serve_enabled": False})

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


def is_tailscale_serving(port: int = DEFAULT_PORT) -> bool:
    """Check if tailscale is currently serving on the given port."""
    # First check if our managed subprocess is running
    if _tailscale_serve_proc is not None and _tailscale_serve_proc.poll() is None:
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

    Args:
        port: The port to serve

    Returns:
        Tuple of (success, message)
    """
    global _tailscale_serve_proc

    if not is_tailscale_available():
        return False, "Tailscale CLI not found. Install Tailscale from https://tailscale.com/download"

    if not is_tailscale_connected():
        return False, "Tailscale is not connected. Run 'tailscale up' to connect."

    # Terminate existing subprocess if any
    if _tailscale_serve_proc is not None and _tailscale_serve_proc.poll() is None:
        _tailscale_serve_proc.terminate()
        try:
            _tailscale_serve_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _tailscale_serve_proc.kill()

    # Start foreground serve (no --bg = ephemeral, dies with process)
    try:
        _tailscale_serve_proc = subprocess.Popen(
            ["tailscale", "serve", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        # Brief delay to check for immediate failure
        import time
        time.sleep(0.5)
        if _tailscale_serve_proc.poll() is not None:
            stderr = _tailscale_serve_proc.stderr.read().decode() if _tailscale_serve_proc.stderr else ""
            return False, f"Failed to start tailscale serve: {stderr}"
    except Exception as e:
        return False, f"Failed to start tailscale serve: {e}"

    return True, f"Tailscale serve enabled for port {port}"


def disable_tailscale_serve() -> tuple[bool, str]:
    """Disable tailscale serve.

    Terminates the tailscale serve subprocess if we started one.

    Returns:
        Tuple of (success, message)
    """
    global _tailscale_serve_proc

    if _tailscale_serve_proc is not None:
        if _tailscale_serve_proc.poll() is None:
            _tailscale_serve_proc.terminate()
            try:
                _tailscale_serve_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _tailscale_serve_proc.kill()
        _tailscale_serve_proc = None
        return True, "Tailscale serve disabled"

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
    # Check if the LaunchAgent service is running
    if is_loaded() and get_pid() is not None:
        status = get_status()
        pid = status.get("pid")
        msg = (
            f"iuselinux service is already running (PID {pid}).\n"
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
    result = subprocess.run(
        ["launchctl", "list", TRAY_SERVICE_LABEL],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    # Parse the output - format is: PID\tStatus\tLabel
    lines = result.stdout.strip().split("\n")
    for line in lines:
        parts = line.split("\t")
        if len(parts) >= 1:
            try:
                return int(parts[0])
            except ValueError:
                return None
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
