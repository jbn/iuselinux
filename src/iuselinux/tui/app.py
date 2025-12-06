"""Main Textual application for iMessage Gateway TUI."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from iuselinux.tui.client import APIClient
from iuselinux.tui.screens.home import HomeScreen


class IMessageApp(App[None]):
    """iMessage Gateway TUI client."""

    TITLE = "iMessage"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("?", "help", "Help"),
        Binding("ctrl+s", "settings", "Settings"),
        Binding("/", "search", "Search"),
        Binding("n", "compose", "New Message"),
    ]

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        token: str | None = None,
    ) -> None:
        """Initialize the app with server connection info."""
        super().__init__()
        self.server_host = host
        self.server_port = port
        self.api_token = token
        self.api = APIClient(host=host, port=port, token=token)

    @property
    def base_url(self) -> str:
        """Get the base URL for API calls."""
        return f"http://{self.server_host}:{self.server_port}"

    async def on_mount(self) -> None:
        """Called when app is mounted."""
        self.push_screen(HomeScreen())
        # Check connection on startup
        await self._check_connection()

    async def _check_connection(self) -> None:
        """Check if we can connect to the server."""
        try:
            health = await self.api.health()
            if health.status == "ok":
                self.notify(f"Connected to {self.server_host}:{self.server_port}")
            else:
                self.notify(f"Server unhealthy: {health.status}", severity="warning")
        except Exception as e:
            self.notify(f"Connection failed: {e}", severity="error")

    def action_help(self) -> None:
        """Show help screen."""
        self.notify("Help: Press q to quit, / to search, n for new message")

    def action_settings(self) -> None:
        """Show settings screen."""
        from iuselinux.tui.screens.settings import SettingsScreen

        self.push_screen(SettingsScreen())

    def action_search(self) -> None:
        """Show search screen."""
        self.notify("Search coming soon")

    def action_compose(self) -> None:
        """Show compose screen for new message."""
        self.notify("Compose coming soon")
