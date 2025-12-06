"""Home screen with chat list and message view."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header

from iuselinux.tui.widgets.chat_list import ChatList, ChatSelected
from iuselinux.tui.widgets.message_list import MessageList
from iuselinux.tui.widgets.message_input import MessageInput, MessageSubmitted

if TYPE_CHECKING:
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

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header()
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

        try:
            success = await app.api.send_message(recipient, event.text)
            if success:
                self.notify("Message sent")
                # Refresh messages to show the sent message
                message_list = self.query_one(MessageList)
                await message_list.load_chat(self._current_chat)
            else:
                self.notify("Failed to send message", severity="error")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

    def action_focus_chat_list(self) -> None:
        """Focus the chat list."""
        chat_list = self.query_one(ChatList)
        chat_list.focus()
