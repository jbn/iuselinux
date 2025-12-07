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

# Number of messages to load per page
PAGE_SIZE = 50


class MessageList(VerticalScroll):
    """Scrollable list of messages in a chat."""

    BINDINGS = [
        Binding("j", "scroll_down", "Scroll Down", show=False),
        Binding("k", "scroll_up", "Scroll Up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
        Binding("pageup", "load_more", "Load More", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.border_title = "Messages"
        self._current_chat: Chat | None = None
        self._messages: list[Message] = []
        self._pending_texts: set[str] = set()  # Track pending message texts
        self._seen_rowids: set[int] = set()  # Track seen message rowids to prevent duplicates
        self._oldest_rowid: int | None = None  # For pagination
        self._has_more: bool = True  # Whether there are more messages to load
        self._loading_more: bool = False  # Prevent concurrent loads

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
        self._oldest_rowid = None
        self._has_more = True
        self._loading_more = False
        self.border_title = f"Messages - {chat.title}"
        self._show_placeholder("Loading messages...")

        app = self.app
        if not isinstance(app, IMessageApp):
            return

        try:
            messages = await app.api.get_messages(chat.rowid, limit=PAGE_SIZE)
            self._messages = messages
            # Track all loaded message rowids
            self._seen_rowids = {m.rowid for m in messages}
            # Track oldest for pagination
            if messages:
                self._oldest_rowid = min(m.rowid for m in messages)
                self._has_more = len(messages) == PAGE_SIZE
            else:
                self._has_more = False
            self._render_messages()
        except Exception as e:
            self._show_placeholder(f"Error loading messages: {e}")

    def _render_messages(self, scroll_to_bottom: bool = True) -> None:
        """Render all messages."""
        self.remove_children()
        if not self._messages:
            self._show_placeholder("No messages in this chat")
            return

        is_group = self._current_chat.is_group if self._current_chat else False

        # Show "load more" indicator at top if there are more messages
        if self._has_more:
            self.mount(Static("↑ Scroll up or press PageUp to load more", classes="load-more-hint"))

        # Messages come in reverse chronological order, reverse for display
        prev_sender: str | None = None
        for msg in reversed(self._messages):
            # Only show sender name if different from previous message
            show_sender = msg.handle_id != prev_sender
            prev_sender = msg.handle_id if not msg.is_from_me else None

            self.mount(MessageBubble(msg, is_group=is_group, show_sender=show_sender))

        # Scroll to bottom for initial load
        if scroll_to_bottom:
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
        is_group = self._current_chat.is_group if self._current_chat else False
        self.mount(MessageBubble(message, is_group=is_group))
        self.scroll_end(animate=True)

    def add_pending_message(self, text: str) -> MessageBubble:
        """Add a pending (optimistic) message while sending.

        Returns the MessageBubble widget so it can be updated on success/failure.
        """
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

        is_group = self._current_chat.is_group if self._current_chat else False
        bubble = MessageBubble(pending_msg, pending=True, is_group=is_group)
        self.mount(bubble)
        self.scroll_end(animate=True)
        return bubble

    def mark_message_failed(self, text: str) -> None:
        """Mark a pending message as failed to send."""
        # Find the pending bubble with this text
        for bubble in self.query(MessageBubble):
            if bubble.pending and bubble.message.text == text:
                bubble.mark_failed()
                # Keep in pending texts so it can be retried
                return

    async def action_load_more(self) -> None:
        """Load older messages (pagination)."""
        await self._load_more_messages()

    async def _load_more_messages(self) -> None:
        """Load more messages before the oldest currently loaded."""
        if not self._has_more or self._loading_more or not self._current_chat:
            return

        if self._oldest_rowid is None:
            return

        from iuselinux.tui.app import IMessageApp

        app = self.app
        if not isinstance(app, IMessageApp):
            return

        self._loading_more = True
        try:
            # Load messages before the oldest we have
            older_messages = await app.api.get_messages(
                self._current_chat.rowid,
                limit=PAGE_SIZE,
                before_rowid=self._oldest_rowid,
            )

            if not older_messages:
                self._has_more = False
                self._loading_more = False
                # Remove load more hint
                hints = self.query(".load-more-hint")
                for h in hints:
                    h.remove()
                return

            # Add to our message list and update tracking
            new_rowids = {m.rowid for m in older_messages}
            self._seen_rowids.update(new_rowids)
            self._messages.extend(older_messages)
            self._oldest_rowid = min(m.rowid for m in older_messages)
            self._has_more = len(older_messages) == PAGE_SIZE

            # Re-render without scrolling to bottom
            self._render_messages(scroll_to_bottom=False)

        except Exception as e:
            logger.error("Failed to load more messages: %s", e)
        finally:
            self._loading_more = False

    def on_scroll_y(self) -> None:
        """Handle scroll events to trigger pagination."""
        # If scrolled near the top, load more
        if self.scroll_offset.y <= 50 and self._has_more and not self._loading_more:
            self.run_worker(self._load_more_messages())
