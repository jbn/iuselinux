"""Message bubble widget for displaying a single message."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Static

from iuselinux.tui.image_renderer import get_renderer
from iuselinux.tui.terminal_graphics import get_terminal_capabilities

if TYPE_CHECKING:
    from iuselinux.tui.models import Attachment, Message


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


class MessageBubble(Vertical):
    """A single message bubble with text and optional attachments."""

    def __init__(
        self,
        message: Message,
        pending: bool = False,
        failed: bool = False,
        is_group: bool = False,
        show_sender: bool = True,
    ) -> None:
        self.message = message
        self.pending = pending
        self.failed = failed
        self.is_group = is_group
        self.show_sender = show_sender
        # Determine style based on sender
        classes = "message-bubble "
        classes += "message-sent" if message.is_from_me else "message-received"
        if pending:
            classes += " pending"
        if failed:
            classes += " failed"
        super().__init__(classes=classes)

    def compose(self):
        """Compose the message bubble contents."""
        from iuselinux.tui.widgets.attachment import AttachmentWidget

        # Text content widget
        yield Static(self.compose_content(), classes="message-text")

        # Check if we have graphics support for inline images
        caps = get_terminal_capabilities()
        renderer = get_renderer(caps)
        has_graphics = renderer is not None

        # Add attachment widgets for images (if graphics supported)
        for att in self.message.attachments:
            if att.is_image and has_graphics:
                yield AttachmentWidget(att)

    def compose_content(self) -> Text:
        """Build the message text content."""
        content = Text()
        msg = self.message

        # Show sender for received messages in group chats
        if not msg.is_from_me and self.show_sender and self.is_group:
            content.append(msg.sender_name, style="bold cyan")
            content.append("\n")

        # Message text (without attachment placeholders if showing inline)
        caps = get_terminal_capabilities()
        renderer = get_renderer(caps)
        has_graphics = renderer is not None

        if has_graphics:
            # Show text only, attachments rendered separately
            text = msg.text or ""
            non_image_attachments = [a for a in msg.attachments if not a.is_image]
            if text:
                content.append(text)
            for att in non_image_attachments:
                if content:
                    content.append("\n")
                if att.is_video:
                    content.append(f"[Video: {att.filename or 'video'}]", style="magenta")
                else:
                    content.append(f"[File: {att.filename or 'attachment'}]", style="yellow")
        else:
            # No graphics - use display_text which includes placeholders
            content.append(msg.display_text)

        # Handle empty content
        if not content.plain:
            # Don't show [Empty message] if we're showing inline images
            if not (has_graphics and any(a.is_image for a in msg.attachments)):
                content.append("[Empty message]", style="dim italic")

        # Timestamp, pending, or failed indicator
        if self.failed:
            content.append("  ", style="")
            content.append("Failed", style="bold red")
        elif self.pending:
            content.append("  Sending...", style="dim")
        elif msg.timestamp:
            time_str = format_message_time(msg.timestamp)
            content.append(f"  {time_str}", style="dim italic")

        return content

    def confirm(self) -> None:
        """Confirm the message was sent - remove pending state."""
        self.pending = False
        self.failed = False
        self.remove_class("pending")
        self.remove_class("failed")
        self._update_text()

    def mark_failed(self) -> None:
        """Mark the message as failed to send."""
        self.pending = False
        self.failed = True
        self.remove_class("pending")
        self.add_class("failed")
        self._update_text()

    def _update_text(self) -> None:
        """Update the text content widget."""
        text_widget = self.query_one(".message-text", Static)
        text_widget.update(self.compose_content())

    def update(self, content) -> None:
        """Override update to update the text widget."""
        # This maintains backward compatibility with code that calls update()
        try:
            text_widget = self.query_one(".message-text", Static)
            text_widget.update(content)
        except Exception:
            # Widget not yet mounted, will be set on mount
            pass
