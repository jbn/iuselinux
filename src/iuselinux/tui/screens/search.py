"""Search screen for finding messages across conversations."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.message import Message as TextualMessage
from textual.screen import Screen
from textual.widgets import Footer, Input, Static

from iuselinux.tui.widgets import AppHeader

if TYPE_CHECKING:
    from iuselinux.tui.app import IMessageApp
    from iuselinux.tui.models import SearchResult


class SearchResultSelected(TextualMessage):
    """Posted when a search result is selected."""

    def __init__(self, result: SearchResult) -> None:
        super().__init__()
        self.result = result


class SearchResultItem(Static):
    """A single search result item with context snippet."""

    DEFAULT_CSS = """
    SearchResultItem {
        width: 100%;
        height: auto;
        padding: 1 2;
        border-bottom: solid $surface;
    }

    SearchResultItem:hover {
        background: $surface;
    }

    SearchResultItem:focus {
        background: $primary 20%;
    }

    SearchResultItem .chat-name {
        text-style: bold;
        color: $primary;
    }

    SearchResultItem .timestamp {
        color: $text-muted;
        text-style: italic;
    }

    SearchResultItem .snippet {
        margin-top: 1;
    }

    SearchResultItem .highlight {
        text-style: bold;
        color: $warning;
    }
    """

    def __init__(self, result: SearchResult, search_query: str) -> None:
        super().__init__()
        self.result = result
        self._search_query = search_query
        self.can_focus = True

    def compose(self) -> ComposeResult:
        """Compose the search result display."""
        msg = self.result.message
        chat = self.result.chat

        # Chat/sender info
        chat_name = chat.title if chat else "Unknown Chat"
        sender = msg.sender_name

        # Timestamp
        time_str = ""
        if msg.timestamp:
            time_str = msg.timestamp.strftime("%Y-%m-%d %H:%M")

        # Get text with highlighted match
        text = msg.text or ""
        snippet = self._get_context_snippet(text, self._search_query)

        yield Static(f"[b]{chat_name}[/b] - {sender}", classes="chat-name")
        yield Static(time_str, classes="timestamp")
        yield Static(snippet, classes="snippet")

    def _get_context_snippet(self, text: str, query: str, context_chars: int = 50) -> str:
        """Extract a snippet around the match with highlighting."""
        if not text or not query:
            return text[:100] + ("..." if len(text) > 100 else "")

        # Case-insensitive search for the query
        lower_text = text.lower()
        lower_query = query.lower()
        idx = lower_text.find(lower_query)

        if idx == -1:
            # Query not found (shouldn't happen for search results)
            return text[:100] + ("..." if len(text) > 100 else "")

        # Calculate snippet bounds
        start = max(0, idx - context_chars)
        end = min(len(text), idx + len(query) + context_chars)

        # Build snippet with highlighting
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""

        # Extract parts
        before = text[start:idx]
        match = text[idx : idx + len(query)]
        after = text[idx + len(query) : end]

        # Format with bold highlighting for the match
        return f"{prefix}{before}[bold yellow]{match}[/bold yellow]{after}{suffix}"

    def on_click(self) -> None:
        """Handle click on result."""
        self.post_message(SearchResultSelected(self.result))

    def on_key(self, event: Any) -> None:
        """Handle key press on focused result."""
        if event.key == "enter":
            self.post_message(SearchResultSelected(self.result))
            event.stop()


class SearchScreen(Screen[None]):
    """Screen for searching messages across all conversations."""

    CSS = """
    SearchScreen {
        layout: vertical;
    }

    #search-container {
        width: 100%;
        height: 1fr;
        padding: 1 2;
    }

    #search-input-container {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }

    #search-input {
        width: 100%;
    }

    #search-status {
        height: auto;
        color: $text-muted;
        margin-bottom: 1;
    }

    #results-container {
        width: 100%;
        height: 1fr;
        border: round $surface;
    }

    #no-results {
        width: 100%;
        height: auto;
        padding: 2;
        text-align: center;
        color: $text-muted;
    }

    #loading {
        width: 100%;
        height: auto;
        padding: 2;
        text-align: center;
        color: $text-muted;
        text-style: italic;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "focus_results", "Results", show=False),
        Binding("up", "focus_input", "Input", show=False),
    ]

    # Debounce delay in seconds
    DEBOUNCE_DELAY = 0.3

    def __init__(self) -> None:
        super().__init__()
        self._results: list[SearchResult] = []
        self._total_count: int = 0
        self._current_query: str = ""
        self._search_task: asyncio.Task[Any] | None = None
        self._debounce_task: asyncio.Task[Any] | None = None

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield AppHeader(title="Search Messages")
        with Container(id="search-container"):
            with Vertical(id="search-input-container"):
                yield Input(
                    placeholder="Search messages...",
                    id="search-input",
                )
            yield Static("Type to search", id="search-status")
            with VerticalScroll(id="results-container"):
                yield Static("Enter a search term to find messages", id="no-results")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the search input when mounted."""
        self.query_one("#search-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes with debouncing."""
        if event.input.id != "search-input":
            return

        query = event.value.strip()

        # Cancel any pending debounce
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        if not query:
            # Clear results immediately
            self._clear_results()
            self._update_status("Type to search")
            return

        # Debounce the search
        self._debounce_task = asyncio.create_task(self._debounced_search(query))

    async def _debounced_search(self, query: str) -> None:
        """Wait for debounce delay, then trigger search."""
        try:
            await asyncio.sleep(self.DEBOUNCE_DELAY)
            await self._do_search(query)
        except asyncio.CancelledError:
            pass

    async def _do_search(self, query: str) -> None:
        """Perform the actual search."""
        from iuselinux.tui.app import IMessageApp

        app = self.app
        if not isinstance(app, IMessageApp):
            return

        # Cancel any existing search
        if self._search_task and not self._search_task.done():
            self._search_task.cancel()

        self._current_query = query
        self._update_status("Searching...")
        self._show_loading()

        try:
            results, total = await app.api.search(query, limit=50)
            self._results = results
            self._total_count = total
            self._display_results(query)
        except Exception as e:
            self._update_status(f"Search failed: {e}")
            self._clear_results()

    def _update_status(self, text: str) -> None:
        """Update the status text."""
        status = self.query_one("#search-status", Static)
        status.update(text)

    def _show_loading(self) -> None:
        """Show loading indicator."""
        container = self.query_one("#results-container", VerticalScroll)
        container.remove_children()
        container.mount(Static("Searching...", id="loading"))

    def _clear_results(self) -> None:
        """Clear the results display."""
        self._results = []
        self._total_count = 0
        container = self.query_one("#results-container", VerticalScroll)
        container.remove_children()
        container.mount(Static("Enter a search term to find messages", id="no-results"))

    def _display_results(self, query: str) -> None:
        """Display search results."""
        container = self.query_one("#results-container", VerticalScroll)
        container.remove_children()

        if not self._results:
            self._update_status("No results found")
            container.mount(
                Static(f"No messages found matching '{query}'", id="no-results")
            )
            return

        # Update status with count
        shown = len(self._results)
        if self._total_count > shown:
            self._update_status(f"Showing {shown} of {self._total_count} results")
        else:
            self._update_status(f"{self._total_count} result{'s' if self._total_count != 1 else ''} found")

        # Add result items
        for result in self._results:
            container.mount(SearchResultItem(result, query))

    def on_search_result_selected(self, event: SearchResultSelected) -> None:
        """Handle selection of a search result."""
        result = event.result

        # Notify user of selection (navigation to be implemented later)
        chat_name = result.chat.title if result.chat else "Unknown"
        self.notify(f"Selected result in '{chat_name}'")

        # For now, just go back to home screen
        # TODO: Navigate to the specific message (iuselinux-qxk.7.4)
        self.app.pop_screen()

    def action_cancel(self) -> None:
        """Cancel and go back."""
        # Cancel any pending tasks
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._search_task and not self._search_task.done():
            self._search_task.cancel()
        self.app.pop_screen()

    def action_focus_results(self) -> None:
        """Focus the first result."""
        try:
            first_result = self.query_one(SearchResultItem)
            first_result.focus()
        except Exception:
            pass

    def action_focus_input(self) -> None:
        """Focus the search input."""
        self.query_one("#search-input", Input).focus()
