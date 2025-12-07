"""Home screen with chat list and message view."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer

from iuselinux.tui.widgets import AppHeader
from iuselinux.tui.widgets.chat_list import ChatList, ChatSelected
from iuselinux.tui.widgets.message_list import MessageList
from iuselinux.tui.widgets.message_input import MessageInput, MessageSubmitted

if TYPE_CHECKING:
    from iuselinux.tui.app import NewMessages
    from iuselinux.tui.models import Chat


class HomeScreen(Screen[None]):
    """Main screen with sidebar chat list and message pane."""

    CSS = """
    HomeScreen {
        layout: horizontal;
    }

    #sidebar {
        width: 30;
        min-width: 20;
        max-width: 50;
        border-right: solid $primary;
    }

    #main-pane {
        width: 1fr;
    }

    #message-area {
        height: 1fr;
    }

    #input-area {
        height: auto;
        max-height: 10;
        dock: bottom;
    }
    """

    BINDINGS = [
        ("escape", "focus_chat_list", "Chat List"),
        ("tab", "focus_next", "Next"),
        ("shift+tab", "focus_previous", "Previous"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_chat: Chat | None = None

    async def on_mount(self) -> None:
        """Initialize the header with server info."""
        from iuselinux.tui.app import IMessageApp

        app = self.app
        if isinstance(app, IMessageApp):
            header = self.query_one(AppHeader)
            header.set_server(f"{app.server_host}:{app.server_port}")

    def set_connection_status(self, connected: bool) -> None:
        """Update the header connection indicator."""
        try:
            header = self.query_one(AppHeader)
            header.set_connected(connected)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield AppHeader(title="iMessage")
        with Horizontal():
            with Vertical(id="sidebar"):
                yield ChatList()
            with Vertical(id="main-pane"):
                with Container(id="message-area"):
                    yield MessageList()
                with Container(id="input-area"):
                    yield MessageInput()
        yield Footer()

    async def on_chat_selected(self, event: ChatSelected) -> None:
        """Handle chat selection."""
        self._current_chat = event.chat
        message_list = self.query_one(MessageList)
        await message_list.load_chat(event.chat)
        # Focus the message input
        message_input = self.query_one(MessageInput)
        message_input.focus()

    async def on_message_submitted(self, event: MessageSubmitted) -> None:
        """Handle message submission."""
        from iuselinux.tui.app import IMessageApp

        if not self._current_chat:
            self.notify("Select a chat first", severity="warning")
            return

        app = self.app
        if not isinstance(app, IMessageApp):
            return

        # Determine recipient - use chat guid for groups, identifier for 1:1
        if self._current_chat.is_group:
            recipient = self._current_chat.guid
        else:
            recipient = self._current_chat.identifier or self._current_chat.guid

        # Add pending message immediately (optimistic UI)
        message_list = self.query_one(MessageList)
        message_list.add_pending_message(event.text)

        try:
            success = await app.api.send_message(recipient, event.text)
            if not success:
                message_list.mark_message_failed(event.text)
                self.notify("Failed to send message", severity="error")
            # WebSocket will push the confirmed message
        except Exception as e:
            message_list.mark_message_failed(event.text)
            self.notify(f"Send failed: {e}", severity="error")

    def on_new_messages(self, event: NewMessages) -> None:
        """Handle new messages from WebSocket."""
        logger.debug(
            "Received %d new messages, current_chat=%s",
            len(event.messages),
            self._current_chat.rowid if self._current_chat else None,
        )
        if not self._current_chat:
            return

        message_list = self.query_one(MessageList)
        chat_list = self.query_one(ChatList)

        # Add messages that belong to the current chat
        for msg in event.messages:
            if msg.chat_id == self._current_chat.rowid:
                logger.debug("Adding message %d to current chat", msg.rowid)
                message_list.add_message(msg)

        # Refresh chat list to update order/preview
        chat_list.refresh_chats()

    def action_focus_chat_list(self) -> None:
        """Focus the chat list."""
        chat_list = self.query_one(ChatList)
        chat_list.focus()

    async def navigate_to_message(self, chat: Chat, message_rowid: int) -> None:
        """Navigate to a specific message in a chat.

        Loads the chat and scrolls to the target message with highlighting.
        """
        self._current_chat = chat
        chat_list = self.query_one(ChatList)
        message_list = self.query_one(MessageList)

        # Select the chat in the sidebar (if it's loaded)
        chat_list.select_chat_by_rowid(chat.rowid)

        # Load messages centered around the target message
        await message_list.load_chat_at_message(chat, message_rowid)
