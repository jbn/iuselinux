"""Custom header widget with connection status."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Static


class ConnectionStatus(Static):
    """Shows WebSocket connection status."""

    connected: reactive[bool] = reactive(False)

    def render(self) -> str:
        if self.connected:
            return "● Connected"
        return "○ Disconnected"

    def watch_connected(self, connected: bool) -> None:
        """Update styling when connection status changes."""
        self.remove_class("connected", "disconnected")
        self.add_class("connected" if connected else "disconnected")


class AppHeader(Static):
    """Application header with title and connection status."""

    DEFAULT_CSS = """
    AppHeader {
        dock: top;
        width: 100%;
        height: 1;
        background: $primary;
        color: $text;
    }

    AppHeader Horizontal {
        width: 100%;
        height: 1;
    }

    AppHeader .header-title {
        width: 1fr;
        padding: 0 1;
        text-style: bold;
    }

    AppHeader .header-server {
        width: auto;
        padding: 0 1;
        color: $text-muted;
    }

    AppHeader ConnectionStatus {
        width: auto;
        padding: 0 1;
    }

    AppHeader ConnectionStatus.connected {
        color: $success;
    }

    AppHeader ConnectionStatus.disconnected {
        color: $warning;
    }
    """

    def __init__(
        self,
        title: str = "iMessage",
        server: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._server = server

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static(self._title, classes="header-title")
            if self._server:
                yield Static(self._server, classes="header-server")
            yield ConnectionStatus()

    def set_connected(self, connected: bool) -> None:
        """Update the connection status indicator."""
        status = self.query_one(ConnectionStatus)
        status.connected = connected

    def set_server(self, server: str) -> None:
        """Update the server display."""
        self._server = server
        try:
            server_widget = self.query_one(".header-server", Static)
            server_widget.update(server)
        except Exception:
            pass
