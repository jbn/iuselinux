"""Main Textual application for iMessage Gateway TUI."""

from __future__ import annotations

import logging

from textual.app import App

logger = logging.getLogger(__name__)
from textual.binding import Binding
from textual.message import Message as TextualMessage

from iuselinux.tui.client import APIClient, WebSocketClient
from iuselinux.tui.models import Message
from iuselinux.tui.screens.home import HomeScreen
from iuselinux.tui.themes import ThemeMode, detect_system_dark_mode


class NewMessages(TextualMessage):
    """Posted when new messages arrive via WebSocket."""

    def __init__(self, messages: list[Message]) -> None:
        super().__init__()
        self.messages = messages


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
        Binding("ctrl+t", "toggle_theme", "Theme"),
    ]

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8000,
        token: str | None = None,
        theme_mode: ThemeMode = ThemeMode.AUTO,
    ) -> None:
        """Initialize the app with server connection info."""
        super().__init__()
        self.server_host = host
        self.server_port = port
        self.api_token = token
        self.api = APIClient(host=host, port=port, token=token)
        self.ws = WebSocketClient(host=host, port=port, token=token)
        self._ws_task: object | None = None
        self._theme_mode = theme_mode
        self._apply_theme()

    @property
    def base_url(self) -> str:
        """Get the base URL for API calls."""
        return f"http://{self.server_host}:{self.server_port}"

    def _apply_theme(self) -> None:
        """Apply the current theme mode."""
        if self._theme_mode == ThemeMode.LIGHT:
            self.theme = "textual-light"
        elif self._theme_mode == ThemeMode.DARK:
            self.theme = "textual-dark"
        else:  # AUTO
            system_dark = detect_system_dark_mode()
            self.theme = "textual-dark" if system_dark else "textual-light"

    def cycle_theme(self) -> None:
        """Cycle through theme modes: auto -> dark -> light -> auto."""
        modes = [ThemeMode.AUTO, ThemeMode.DARK, ThemeMode.LIGHT]
        current_idx = modes.index(self._theme_mode)
        self._theme_mode = modes[(current_idx + 1) % len(modes)]
        self._apply_theme()
        self.notify(f"Theme: {self._theme_mode.value}")

    async def on_mount(self) -> None:
        """Called when app is mounted."""
        self.push_screen(HomeScreen())
        # Check connection and start WebSocket
        await self._check_connection()
        self._start_websocket()

    def _start_websocket(self) -> None:
        """Start WebSocket listener in background."""
        import asyncio

        async def ws_listener() -> None:
            def on_messages(messages: list[Message]) -> None:
                logger.debug("WebSocket callback: %d messages", len(messages))
                self.post_message(NewMessages(messages))

            def on_connected() -> None:
                self.notify("Real-time updates connected")
                self._update_connection_status(True)

            def on_disconnected() -> None:
                self.notify("Real-time updates disconnected", severity="warning")
                self._update_connection_status(False)

            await self.ws.listen(
                on_messages=on_messages,
                on_connected=on_connected,
                on_disconnected=on_disconnected,
            )

        self._ws_task = asyncio.create_task(ws_listener())

    def _update_connection_status(self, connected: bool) -> None:
        """Update connection status on the current screen."""
        screen = self.screen
        if hasattr(screen, "set_connection_status"):
            screen.set_connection_status(connected)

    async def on_unmount(self) -> None:
        """Called when app is unmounting."""
        self.ws.stop()
        await self.ws.disconnect()

    def on_new_messages(self, event: NewMessages) -> None:
        """Forward new messages to the current screen."""
        logger.debug("Forwarding %d messages to screen", len(event.messages))
        screen = self.screen
        if screen is not None:
            screen.post_message(event)

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
        from iuselinux.tui.screens.compose import ComposeScreen

        self.push_screen(ComposeScreen())

    def action_toggle_theme(self) -> None:
        """Cycle through theme modes."""
        self.cycle_theme()
