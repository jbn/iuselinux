"""Message bubble widget for displaying a single message."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from iuselinux.tui.models import Message


class MessageBubble(Static):
    """A single message bubble."""

    def __init__(self, message: Message, pending: bool = False) -> None:
        self.message = message
        self.pending = pending
        # Determine style based on sender
        classes = "message-bubble "
        classes += "message-sent" if message.is_from_me else "message-received"
        if pending:
            classes += " pending"
        super().__init__(classes=classes)

    def compose_content(self) -> Text:
        """Build the message content."""
        content = Text()
        msg = self.message

        # Show sender for received messages
        if not msg.is_from_me:
            content.append(msg.sender_name, style="bold")
            content.append("\n")

        # Message text
        content.append(msg.display_text)

        # Timestamp or pending indicator
        if self.pending:
            content.append("\nSending...", style="dim italic")
        elif msg.timestamp:
            time_str = msg.timestamp.strftime("%H:%M")
            content.append(f"\n{time_str}", style="dim italic")

        return content

    def confirm(self) -> None:
        """Confirm the message was sent - remove pending state."""
        self.pending = False
        self.remove_class("pending")
        self.update(self.compose_content())

    def on_mount(self) -> None:
        """Render the message when mounted."""
        self.update(self.compose_content())
