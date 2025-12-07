"""Compose screen for starting new conversations."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Static

from iuselinux.tui.widgets import AppHeader

if TYPE_CHECKING:
    from iuselinux.tui.app import IMessageApp


# Validation patterns (match API patterns)
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{6,14}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_recipient(value: str) -> str | None:
    """Validate a recipient phone number or email.

    Returns None if valid, or an error message if invalid.
    """
    value = value.strip()
    if not value:
        return "Recipient is required"

    # Normalize phone numbers (remove formatting)
    normalized = re.sub(r"[\s\-\(\)]", "", value)

    if PHONE_PATTERN.match(normalized):
        return None  # Valid phone
    if EMAIL_PATTERN.match(value):
        return None  # Valid email

    return "Enter a valid phone number or email"


def normalize_recipient(value: str) -> str:
    """Normalize recipient for sending.

    Removes phone formatting, keeps emails as-is.
    """
    value = value.strip()
    normalized = re.sub(r"[\s\-\(\)]", "", value)
    if PHONE_PATTERN.match(normalized):
        return normalized
    return value


class ComposeScreen(Screen[None]):
    """Screen for composing a new message to a new recipient."""

    CSS = """
    ComposeScreen {
        layout: vertical;
    }

    #compose-container {
        width: 100%;
        height: 1fr;
        padding: 2 4;
    }

    #compose-form {
        width: 100%;
        max-width: 80;
        margin: 0 auto;
    }

    .form-label {
        margin-top: 1;
        margin-bottom: 0;
    }

    #recipient-input {
        width: 100%;
        margin-bottom: 1;
    }

    #message-input {
        width: 100%;
        height: 5;
        margin-bottom: 1;
    }

    #error-message {
        color: $error;
        height: auto;
        margin-bottom: 1;
    }

    #button-row {
        width: 100%;
        layout: horizontal;
        height: auto;
    }

    #send-button {
        margin-right: 1;
    }

    #cancel-button {
        margin-left: 1;
    }

    .sending-indicator {
        color: $text-muted;
        text-style: italic;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+enter", "send", "Send"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._sending = False

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield AppHeader(title="New Message")
        with Container(id="compose-container"):
            with Vertical(id="compose-form"):
                yield Static("To:", classes="form-label")
                yield Input(
                    placeholder="Phone number or email",
                    id="recipient-input",
                )
                yield Static("Message:", classes="form-label")
                yield Input(
                    placeholder="Type your message...",
                    id="message-input",
                )
                yield Static("", id="error-message")
                with Container(id="button-row"):
                    yield Button("Send", id="send-button", variant="primary")
                    yield Button("Cancel", id="cancel-button", variant="default")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the recipient input when mounted."""
        self.query_one("#recipient-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "send-button":
            self.action_send()
        elif event.button.id == "cancel-button":
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in inputs."""
        if event.input.id == "recipient-input":
            # Move to message input
            self.query_one("#message-input", Input).focus()
        elif event.input.id == "message-input":
            # Send the message
            self.action_send()

    def _show_error(self, message: str) -> None:
        """Show an error message."""
        error_widget = self.query_one("#error-message", Static)
        error_widget.update(message)

    def _clear_error(self) -> None:
        """Clear the error message."""
        error_widget = self.query_one("#error-message", Static)
        error_widget.update("")

    def _set_sending(self, sending: bool) -> None:
        """Update UI to reflect sending state."""
        self._sending = sending
        send_button = self.query_one("#send-button", Button)
        recipient_input = self.query_one("#recipient-input", Input)
        message_input = self.query_one("#message-input", Input)

        if sending:
            send_button.label = "Sending..."
            send_button.disabled = True
            recipient_input.disabled = True
            message_input.disabled = True
        else:
            send_button.label = "Send"
            send_button.disabled = False
            recipient_input.disabled = False
            message_input.disabled = False

    def action_cancel(self) -> None:
        """Cancel and go back."""
        if not self._sending:
            self.app.pop_screen()

    def action_send(self) -> None:
        """Send the message."""
        if self._sending:
            return

        recipient_input = self.query_one("#recipient-input", Input)
        message_input = self.query_one("#message-input", Input)

        recipient = recipient_input.value.strip()
        message = message_input.value.strip()

        # Validate recipient
        error = validate_recipient(recipient)
        if error:
            self._show_error(error)
            recipient_input.focus()
            return

        # Validate message
        if not message:
            self._show_error("Message cannot be empty")
            message_input.focus()
            return

        self._clear_error()

        # Send the message asynchronously
        self.run_worker(self._send_message(recipient, message))

    async def _send_message(self, recipient: str, message: str) -> None:
        """Send the message via API."""
        from iuselinux.tui.app import IMessageApp

        app = self.app
        if not isinstance(app, IMessageApp):
            return

        self._set_sending(True)

        try:
            # Normalize recipient
            normalized = normalize_recipient(recipient)
            success = await app.api.send_message(normalized, message)

            if success:
                self.notify(f"Message sent to {recipient}")
                # Go back to home screen
                self.app.pop_screen()
            else:
                self._show_error("Failed to send message")
                self._set_sending(False)
        except Exception as e:
            self._show_error(f"Error: {e}")
            self._set_sending(False)
