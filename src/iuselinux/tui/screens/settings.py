"""Settings screen for TUI configuration."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select

from iuselinux.config import get_config, update_config


class SettingsScreen(Screen[None]):
    """Settings configuration screen."""

    CSS = """
    SettingsScreen {
        align: center middle;
    }

    #settings-container {
        width: 60;
        height: auto;
        max-height: 80%;
        border: round $primary;
        padding: 1 2;
    }

    .settings-title {
        text-style: bold;
        text-align: center;
        width: 100%;
        margin-bottom: 1;
    }

    .settings-label {
        margin-top: 1;
    }

    .settings-input {
        margin-bottom: 1;
    }

    #button-row {
        margin-top: 2;
        height: auto;
        align: center middle;
    }

    #button-row Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
    ]

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        config = get_config()

        yield Header()
        with Center():
            with Vertical(id="settings-container"):
                yield Label("Settings", classes="settings-title")

                yield Label("Server Host:", classes="settings-label")
                yield Input(
                    value=config.get("tui_server_host", "localhost"),
                    placeholder="localhost",
                    id="host-input",
                    classes="settings-input",
                )

                yield Label("Server Port:", classes="settings-label")
                yield Input(
                    value=str(config.get("tui_server_port", 8000)),
                    placeholder="8000",
                    id="port-input",
                    classes="settings-input",
                )

                yield Label("API Token:", classes="settings-label")
                yield Input(
                    value=config.get("api_token", ""),
                    placeholder="(optional)",
                    password=True,
                    id="token-input",
                    classes="settings-input",
                )

                yield Label("Theme:", classes="settings-label")
                yield Select(
                    [
                        ("Auto (system)", "auto"),
                        ("Light", "light"),
                        ("Dark", "dark"),
                    ],
                    value=config.get("tui_theme", "auto"),
                    id="theme-select",
                    classes="settings-input",
                )

                with Center(id="button-row"):
                    yield Button("Save", variant="primary", id="save-btn")
                    yield Button("Cancel", variant="default", id="cancel-btn")

        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "save-btn":
            self.action_save()
        elif event.button.id == "cancel-btn":
            self.action_cancel()

    def action_save(self) -> None:
        """Save settings and return to home."""
        host_input = self.query_one("#host-input", Input)
        port_input = self.query_one("#port-input", Input)
        token_input = self.query_one("#token-input", Input)
        theme_select = self.query_one("#theme-select", Select)

        try:
            port = int(port_input.value)
        except ValueError:
            self.notify("Invalid port number", severity="error")
            return

        updates = {
            "tui_server_host": host_input.value,
            "tui_server_port": port,
            "api_token": token_input.value,
            "tui_theme": str(theme_select.value),
        }

        update_config(updates)
        self.notify("Settings saved. Restart to apply connection changes.")
        self.app.pop_screen()

    def action_cancel(self) -> None:
        """Cancel and return to home."""
        self.app.pop_screen()
