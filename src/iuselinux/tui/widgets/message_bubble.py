"""Message bubble widget for displaying a single message."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static

if TYPE_CHECKING:
    from iuselinux.tui.models import Message


def format_message_time(dt: datetime | None, show_date: bool = False) -> str:
    """Format timestamp for message display.

    Args:
        dt: The timestamp to format
        show_date: If True, include the date for older messages
    """
    if not dt:
        return ""
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    diff = now - dt

    time_str = dt.strftime("%H:%M")

    if show_date:
        if diff.days == 0:
            return time_str
        elif diff.days == 1:
            return f"Yesterday {time_str}"
        elif diff.days < 7:
            return dt.strftime("%a %H:%M")
        else:
            return dt.strftime("%b %d, %H:%M")
    return time_str


class MessageBubble(Static):
    """A single message bubble."""

    def __init__(
        self,
        message: Message,
        pending: bool = False,
        is_group: bool = False,
        show_sender: bool = True,
    ) -> None:
        self.message = message
        self.pending = pending
        self.is_group = is_group
        self.show_sender = show_sender
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

        # Show sender for received messages in group chats
        if not msg.is_from_me and self.show_sender and self.is_group:
            content.append(msg.sender_name, style="bold cyan")
            content.append("\n")

        # Message text
        content.append(msg.display_text)

        # Timestamp or pending indicator
        if self.pending:
            content.append("  ⏳", style="dim")
        elif msg.timestamp:
            time_str = format_message_time(msg.timestamp)
            content.append(f"  {time_str}", style="dim italic")

        return content

    def confirm(self) -> None:
        """Confirm the message was sent - remove pending state."""
        self.pending = False
        self.remove_class("pending")
        self.update(self.compose_content())

    def on_mount(self) -> None:
        """Render the message when mounted."""
        self.update(self.compose_content())
