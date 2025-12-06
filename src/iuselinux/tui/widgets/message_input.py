"""Message input widget for composing messages."""

from __future__ import annotations

from textual.binding import Binding
from textual.events import Key
from textual.message import Message
from textual.widgets import TextArea


class MessageSubmitted(Message):
    """Posted when a message is submitted."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class MessageInput(TextArea):
    """Text input for composing messages."""

    BINDINGS = [
        Binding("ctrl+enter", "newline", "New Line", show=False),
        Binding("escape", "blur", "Cancel", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.border_title = "Message (Enter to send, Ctrl+Enter for newline)"
        self.show_line_numbers = False

    def _on_key(self, event: Key) -> None:
        """Handle key events - Enter sends, Ctrl+Enter for newline."""
        # event.key is "enter" for plain Enter, "ctrl+enter" for Ctrl+Enter
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self._submit()

    def _submit(self) -> None:
        """Submit the message."""
        text = self.text.strip()
        if text:
            self.post_message(MessageSubmitted(text))
            self.clear()

    def action_newline(self) -> None:
        """Insert a newline."""
        self.insert("\n")

    def on_mount(self) -> None:
        """Set placeholder text."""
        self.placeholder = "Type a message..."
