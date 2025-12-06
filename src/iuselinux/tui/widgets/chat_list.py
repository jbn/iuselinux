"""Chat list widget for sidebar."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from iuselinux.tui.models import Chat


def _format_time(dt: datetime | None) -> str:
    """Format timestamp for display."""
    if not dt:
        return ""
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    diff = now - dt
    if diff.days == 0:
        return dt.strftime("%H:%M")
    elif diff.days == 1:
        return "Yesterday"
    elif diff.days < 7:
        return dt.strftime("%a")
    else:
        return dt.strftime("%b %d")


class ChatListItem(Option):
    """A single chat in the list."""

    def __init__(self, chat: Chat) -> None:
        self.chat = chat
        # Build rich text display
        content = Text()
        content.append(chat.title, style="bold")
        content.append("\n")
        if chat.preview:
            preview = chat.preview[:40] + "..." if len(chat.preview) > 40 else chat.preview
            content.append(preview, style="dim")
        time_str = _format_time(chat.last_message_time)
        if time_str:
            content.append(f"  {time_str}", style="dim italic")
        super().__init__(content, id=str(chat.rowid))


class ChatSelected(Message):
    """Posted when a chat is selected."""

    def __init__(self, chat: Chat) -> None:
        super().__init__()
        self.chat = chat


class ChatList(OptionList):
    """List of chats in the sidebar."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "first", "First", show=False),
        Binding("G", "last", "Last", show=False),
        Binding("enter", "select", "Select"),
        Binding("r", "refresh", "Refresh", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.border_title = "Chats"
        self._chats: dict[str, Chat] = {}

    async def on_mount(self) -> None:
        """Load chats when mounted."""
        self.add_option(Option("Loading...", id="loading", disabled=True))
        await self.load_chats()

    async def load_chats(self) -> None:
        """Load chats from the API."""
        from iuselinux.tui.app import IMessageApp

        app = self.app
        if not isinstance(app, IMessageApp):
            return

        try:
            chats = await app.api.get_chats(limit=100)
            self.clear_options()
            self._chats.clear()

            if not chats:
                self.add_option(Option("No chats", id="empty", disabled=True))
                return

            for chat in chats:
                self._chats[str(chat.rowid)] = chat
                self.add_option(ChatListItem(chat))

        except Exception as e:
            self.clear_options()
            self.add_option(Option(f"Error: {e}", id="error", disabled=True))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle chat selection."""
        chat_id = event.option_id
        if chat_id and chat_id in self._chats:
            self.post_message(ChatSelected(self._chats[chat_id]))

    async def action_refresh(self) -> None:
        """Refresh the chat list."""
        await self.load_chats()

    def action_first(self) -> None:
        """Jump to first item."""
        if self.option_count > 0:
            self.highlighted = 0

    def action_last(self) -> None:
        """Jump to last item."""
        if self.option_count > 0:
            self.highlighted = self.option_count - 1
