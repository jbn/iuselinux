"""Message input widget for composing messages."""

from __future__ import annotations

from textual.binding import Binding
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
        Binding("enter", "submit", "Send", show=True),
        Binding("escape", "blur", "Cancel", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.border_title = "Message"
        # Single line by default, grows as needed
        self.show_line_numbers = False

    def action_submit(self) -> None:
        """Submit the message."""
        text = self.text.strip()
        if text:
            self.post_message(MessageSubmitted(text))
            self.clear()

    def on_mount(self) -> None:
        """Set placeholder text."""
        self.placeholder = "Type a message..."
