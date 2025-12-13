"""macOS menu bar tray application for iuselinux."""

import logging
import subprocess
import sys
from typing import Any

import rumps

from .config import get_config_value
from .service import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    get_pid,
    get_plist_path,
    get_tray_plist_path,
    is_loaded,
    is_tray_loaded,
)

logger = logging.getLogger("iuselinux.tray")

# Embedded server process (when running without LaunchAgent)
_embedded_server_proc: subprocess.Popen[bytes] | None = None


class IUseLinuxTrayApp(rumps.App):  # type: ignore[misc]
    """Menu bar tray application for iUseLinux."""

    def __init__(self) -> None:
        super().__init__(
            name="iUseLinux",
            title="iUseLinux",
            quit_button=None,  # Custom quit handling
        )
        self._setup_menu()

    def _setup_menu(self) -> None:
        """Initialize menu items."""
        self.status_item = rumps.MenuItem("Service: Checking...")
        self.toggle_item = rumps.MenuItem("Start Service", callback=self.toggle_service)
        self.run_now_item = rumps.MenuItem("Run Server Now", callback=self.run_server_now)
        self.open_ui_item = rumps.MenuItem("Open Web UI", callback=self.open_web_ui)
        self.hide_item = rumps.MenuItem("Hide Menu Bar Icon", callback=self.hide_tray)
        self.quit_item = rumps.MenuItem("Quit", callback=self.quit_app)

        self.menu = [
            self.status_item,
            self.toggle_item,
            self.run_now_item,
            None,  # Separator
            self.open_ui_item,
            None,  # Separator
            self.hide_item,
            self.quit_item,
        ]

    @rumps.timer(5)  # type: ignore[untyped-decorator]
    def update_status(self, _: Any = None) -> None:
        """Update menu items based on service status."""
        global _embedded_server_proc

        service_running = is_loaded() and get_pid() is not None
        embedded_running = (
            _embedded_server_proc is not None
            and _embedded_server_proc.poll() is None
        )

        if service_running:
            pid = get_pid()
            self.status_item.title = f"Service: Running (PID {pid})"
            self.toggle_item.title = "Stop Service"
            self.run_now_item.title = "Run Server Now (service active)"
            self.run_now_item.set_callback(None)  # Disable
        elif embedded_running and _embedded_server_proc is not None:
            self.status_item.title = (
                f"Server: Running (embedded, PID {_embedded_server_proc.pid})"
            )
            self.toggle_item.title = "Start Service"
            self.run_now_item.title = "Stop Embedded Server"
            self.run_now_item.set_callback(self.stop_embedded_server)
        else:
            self.status_item.title = "Service: Stopped"
            self.toggle_item.title = "Start Service"
            self.run_now_item.title = "Run Server Now"
            self.run_now_item.set_callback(self.run_server_now)

    def toggle_service(self, _: rumps.MenuItem) -> None:
        """Start or stop the LaunchAgent service."""
        plist_path = get_plist_path()

        if is_loaded():
            # Stop service
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
            )
        else:
            # Start service (must be installed)
            if plist_path.exists():
                subprocess.run(
                    ["launchctl", "load", str(plist_path)],
                    capture_output=True,
                )
            else:
                rumps.alert(
                    "Service Not Installed",
                    "Run 'iuselinux service install' first.",
                )
        self.update_status()

    def run_server_now(self, _: rumps.MenuItem) -> None:
        """Run the server in foreground (embedded) mode."""
        global _embedded_server_proc

        if _embedded_server_proc is not None and _embedded_server_proc.poll() is None:
            return  # Already running

        # Start embedded server
        host = DEFAULT_HOST
        port = int(get_config_value("tailscale_serve_port") or DEFAULT_PORT)

        _embedded_server_proc = subprocess.Popen(
            [sys.executable, "-m", "iuselinux", "--host", host, "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.update_status()

    def stop_embedded_server(self, _: rumps.MenuItem) -> None:
        """Stop the embedded server."""
        global _embedded_server_proc
        if _embedded_server_proc is not None:
            _embedded_server_proc.terminate()
            try:
                _embedded_server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _embedded_server_proc.kill()
            _embedded_server_proc = None
        self.update_status()

    def open_web_ui(self, _: rumps.MenuItem) -> None:
        """Open the web UI in default browser."""
        port = int(get_config_value("tailscale_serve_port") or DEFAULT_PORT)
        subprocess.run(["open", f"http://localhost:{port}"])

    def hide_tray(self, _: rumps.MenuItem) -> None:
        """Hide the menu bar icon by unloading tray LaunchAgent."""
        tray_plist = get_tray_plist_path()
        if tray_plist.exists() and is_tray_loaded():
            subprocess.run(
                ["launchctl", "unload", str(tray_plist)],
                capture_output=True,
            )
        rumps.quit_application()

    def quit_app(self, _: rumps.MenuItem) -> None:
        """Quit the tray application."""
        global _embedded_server_proc
        # Stop embedded server if running
        if _embedded_server_proc is not None and _embedded_server_proc.poll() is None:
            _embedded_server_proc.terminate()
            try:
                _embedded_server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _embedded_server_proc.kill()
        rumps.quit_application()


def run_tray() -> None:
    """Run the tray application."""
    app = IUseLinuxTrayApp()
    app.run()
