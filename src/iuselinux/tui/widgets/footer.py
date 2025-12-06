"""Custom footer widget with keybinding hints."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class KeyHint(Static):
    """A single keybinding hint."""

    DEFAULT_CSS = """
    KeyHint {
        width: auto;
        height: 1;
        padding: 0 1;
    }

    KeyHint .key {
        background: $primary;
        color: $text;
        padding: 0 1;
    }

    KeyHint .description {
        color: $text-muted;
        padding: 0 1 0 0;
    }
    """

    def __init__(self, key: str, description: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._key = key
        self._description = description

    def compose(self) -> ComposeResult:
        yield Static(self._key, classes="key")
        yield Static(self._description, classes="description")


class AppFooter(Static):
    """Application footer with context-sensitive keybinding hints."""

    DEFAULT_CSS = """
    AppFooter {
        dock: bottom;
        width: 100%;
        height: 1;
        background: $surface-darken-2;
    }

    AppFooter Horizontal {
        width: 100%;
        height: 1;
    }
    """

    # Default hints shown everywhere
    DEFAULT_HINTS = [
        ("q", "Quit"),
        ("?", "Help"),
        ("n", "New"),
        ("/", "Search"),
        ("Ctrl+S", "Settings"),
    ]

    # Context-specific hints
    CHAT_LIST_HINTS = [
        ("↑↓", "Navigate"),
        ("Enter", "Select"),
        ("Tab", "Messages"),
    ]

    MESSAGE_LIST_HINTS = [
        ("↑↓", "Scroll"),
        ("Esc", "Chats"),
        ("Tab", "Input"),
    ]

    INPUT_HINTS = [
        ("Enter", "Send"),
        ("Esc", "Chats"),
        ("Shift+Tab", "Messages"),
    ]

    def __init__(self, hint_context: str = "default", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._hint_context = hint_context

    def compose(self) -> ComposeResult:
        with Horizontal():
            for key, desc in self._get_hints():
                yield KeyHint(key, desc)

    def _get_hints(self) -> list[tuple[str, str]]:
        """Get hints for the current context."""
        context_hints: dict[str, list[tuple[str, str]]] = {
            "chat_list": self.CHAT_LIST_HINTS,
            "message_list": self.MESSAGE_LIST_HINTS,
            "input": self.INPUT_HINTS,
        }
        hints = context_hints.get(self._hint_context, [])
        # Combine context hints with defaults (space permitting)
        return hints + self.DEFAULT_HINTS[:3]

    def set_context(self, hint_context: str) -> None:
        """Update the footer for a new context."""
        if hint_context != self._hint_context:
            self._hint_context = hint_context
            self.refresh(recompose=True)
