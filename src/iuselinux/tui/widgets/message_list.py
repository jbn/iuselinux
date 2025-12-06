"""Message list widget for displaying chat messages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from iuselinux.tui.widgets.message_bubble import MessageBubble

if TYPE_CHECKING:
    from iuselinux.tui.models import Chat, Message


class MessageList(VerticalScroll):
    """Scrollable list of messages in a chat."""

    BINDINGS = [
        Binding("j", "scroll_down", "Scroll Down", show=False),
        Binding("k", "scroll_up", "Scroll Up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.border_title = "Messages"
        self._current_chat: Chat | None = None
        self._messages: list[Message] = []

    def on_mount(self) -> None:
        """Show placeholder when mounted."""
        self._show_placeholder("Select a chat to view messages")

    def _show_placeholder(self, text: str) -> None:
        """Show a placeholder message."""
        self.remove_children()
        self.mount(Static(text, classes="placeholder"))

    async def load_chat(self, chat: Chat) -> None:
        """Load messages for a chat."""
        from iuselinux.tui.app import IMessageApp

        self._current_chat = chat
        self.border_title = f"Messages - {chat.title}"
        self._show_placeholder("Loading messages...")

        app = self.app
        if not isinstance(app, IMessageApp):
            return

        try:
            messages = await app.api.get_messages(chat.rowid, limit=100)
            self._messages = messages
            self._render_messages()
        except Exception as e:
            self._show_placeholder(f"Error loading messages: {e}")

    def _render_messages(self) -> None:
        """Render all messages."""
        self.remove_children()
        if not self._messages:
            self._show_placeholder("No messages in this chat")
            return

        # Messages come in reverse chronological order, reverse for display
        for msg in reversed(self._messages):
            self.mount(MessageBubble(msg))

        # Scroll to bottom
        self.scroll_end(animate=False)

    def add_message(self, message: Message) -> None:
        """Add a new message to the display."""
        self._messages.insert(0, message)  # Add to start (newest)
        # Remove placeholder if present
        placeholders = self.query(".placeholder")
        for p in placeholders:
            p.remove()
        self.mount(MessageBubble(message))
        self.scroll_end(animate=True)
