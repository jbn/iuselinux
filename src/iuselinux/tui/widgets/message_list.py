"""Message list widget for displaying chat messages."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from iuselinux.tui.widgets.message_bubble import MessageBubble

if TYPE_CHECKING:
    from iuselinux.tui.models import Chat, Message

logger = logging.getLogger(__name__)


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
        self._pending_texts: set[str] = set()  # Track pending message texts
        self._seen_rowids: set[int] = set()  # Track seen message rowids to prevent duplicates

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
        self._pending_texts.clear()  # Clear pending messages when switching chats
        self._seen_rowids.clear()  # Clear seen rowids when switching chats
        self.border_title = f"Messages - {chat.title}"
        self._show_placeholder("Loading messages...")

        app = self.app
        if not isinstance(app, IMessageApp):
            return

        try:
            messages = await app.api.get_messages(chat.rowid, limit=100)
            self._messages = messages
            # Track all loaded message rowids
            self._seen_rowids = {m.rowid for m in messages}
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
        """Add a new message from WebSocket (confirmed message)."""
        # Skip if we've already seen this message
        if message.rowid in self._seen_rowids:
            logger.debug("Skipping duplicate message rowid=%d", message.rowid)
            return

        # Check if this confirms a pending message
        msg_text = message.text or ""
        logger.debug(
            "add_message: rowid=%d is_from_me=%s text=%r pending_texts=%r",
            message.rowid, message.is_from_me, msg_text[:30], self._pending_texts
        )
        if message.is_from_me and msg_text in self._pending_texts:
            logger.debug("Confirming pending message: %r", msg_text[:30])
            self._pending_texts.discard(msg_text)
            self._seen_rowids.add(message.rowid)
            # Find and confirm the pending bubble
            for bubble in self.query(MessageBubble):
                if bubble.pending and bubble.message.text == msg_text:
                    bubble.message = message  # Update with confirmed message
                    bubble.confirm()
                    logger.debug("Confirmed pending bubble")
                    return
            logger.debug("No matching pending bubble found!")

        self._seen_rowids.add(message.rowid)
        self._messages.insert(0, message)  # Add to start (newest)
        # Remove placeholder if present
        placeholders = self.query(".placeholder")
        for p in placeholders:
            p.remove()
        self.mount(MessageBubble(message))
        self.scroll_end(animate=True)

    def add_pending_message(self, text: str) -> None:
        """Add a pending (optimistic) message while sending."""
        from datetime import datetime
        from iuselinux.tui.models import Message

        # Create a temporary message object
        pending_msg = Message(
            rowid=-1,  # Temporary ID
            guid="pending",
            text=text,
            timestamp=datetime.now(),
            is_from_me=True,
            handle_id=None,
            chat_id=self._current_chat.rowid if self._current_chat else None,
        )

        self._pending_texts.add(text)

        # Remove placeholder if present
        placeholders = self.query(".placeholder")
        for p in placeholders:
            p.remove()

        self.mount(MessageBubble(pending_msg, pending=True))
        self.scroll_end(animate=True)
