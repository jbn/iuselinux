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
        self.ws = WebSocketClient(host=host, port=port, token=token)
        self._ws_task: object | None = None

    @property
    def base_url(self) -> str:
        """Get the base URL for API calls."""
        return f"http://{self.server_host}:{self.server_port}"

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
                self.call_from_thread(
                    lambda: self.post_message(NewMessages(messages))
                )

            def on_connected() -> None:
                self.call_from_thread(
                    lambda: self.notify("Real-time updates connected")
                )

            def on_disconnected() -> None:
                self.call_from_thread(
                    lambda: self.notify("Real-time updates disconnected", severity="warning")
                )

            await self.ws.listen(
                on_messages=on_messages,
                on_connected=on_connected,
                on_disconnected=on_disconnected,
            )

        self._ws_task = asyncio.create_task(ws_listener())

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
        self.notify("Compose coming soon")
