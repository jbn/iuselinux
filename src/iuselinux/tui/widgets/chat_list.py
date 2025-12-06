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


def format_relative_time(dt: datetime | None) -> str:
    """Format timestamp as relative time for chat list."""
    if not dt:
        return ""
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    diff = now - dt
    if diff.days == 0:
        if diff.seconds < 60:
            return "now"
        elif diff.seconds < 3600:
            mins = diff.seconds // 60
            return f"{mins}m"
        else:
            return dt.strftime("%H:%M")
    elif diff.days == 1:
        return "Yesterday"
    elif diff.days < 7:
        return dt.strftime("%a")
    elif diff.days < 365:
        return dt.strftime("%b %d")
    else:
        return dt.strftime("%b %d, %Y")


class ChatListItem(Option):
    """A single chat in the list."""

    def __init__(self, chat: Chat, unread_count: int = 0) -> None:
        self.chat = chat
        self.unread_count = unread_count
        # Build rich text display
        content = Text()

        # First line: title and time
        if unread_count > 0:
            content.append("● ", style="bold blue")
        content.append(chat.title, style="bold" if unread_count > 0 else "")

        time_str = format_relative_time(chat.last_message_time)
        if time_str:
            # Right-align time on same line conceptually (show after title)
            content.append(f"  {time_str}", style="dim italic")

        content.append("\n")

        # Second line: preview with unread badge
        if chat.preview:
            preview = chat.preview[:35] + "..." if len(chat.preview) > 35 else chat.preview
            style = "" if unread_count > 0 else "dim"
            content.append(preview, style=style)

        if unread_count > 1:
            content.append(f" ({unread_count})", style="bold blue")

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

    def refresh_chats(self) -> None:
        """Trigger a chat list refresh (called when new messages arrive)."""
        self.run_worker(self.load_chats())
