"""Tests for the search screen."""

from datetime import datetime

import pytest

from iuselinux.tui.models import Chat, Message, SearchResult
from iuselinux.tui.screens.search import SearchResultItem


class TestSearchResultItem:
    """Tests for SearchResultItem widget."""

    def _make_result(
        self,
        text: str = "Hello world",
        chat_name: str = "Test Chat",
        sender: str = "John",
        is_from_me: bool = False,
    ) -> SearchResult:
        """Create a test search result."""
        msg = Message(
            rowid=1,
            guid="test-guid",
            text=text,
            timestamp=datetime(2024, 1, 15, 10, 30),
            is_from_me=is_from_me,
            handle_id="test@example.com",
            chat_id=1,
        )
        chat = Chat(
            rowid=1,
            guid="chat-guid",
            display_name=chat_name,
            identifier="test@example.com",
            last_message_time=datetime(2024, 1, 15, 10, 30),
        )
        return SearchResult(message=msg, chat=chat)

    def test_get_context_snippet_highlights_match(self) -> None:
        """Should highlight the matching text in bold yellow."""
        result = self._make_result(text="The quick brown fox jumps")
        item = SearchResultItem(result, search_query="brown")
        snippet = item._get_context_snippet("The quick brown fox jumps", "brown")
        assert "[bold yellow]brown[/bold yellow]" in snippet
        assert "quick" in snippet
        assert "fox" in snippet

    def test_get_context_snippet_case_insensitive(self) -> None:
        """Should find match regardless of case."""
        result = self._make_result(text="Hello World")
        item = SearchResultItem(result, search_query="hello")
        snippet = item._get_context_snippet("Hello World", "hello")
        # Should highlight the original case "Hello"
        assert "[bold yellow]Hello[/bold yellow]" in snippet

    def test_get_context_snippet_truncates_long_text(self) -> None:
        """Should truncate long text with ellipsis."""
        long_text = "A" * 100 + "match" + "B" * 100
        result = self._make_result(text=long_text)
        item = SearchResultItem(result, search_query="match")
        snippet = item._get_context_snippet(long_text, "match", context_chars=20)
        assert "..." in snippet
        assert "[bold yellow]match[/bold yellow]" in snippet

    def test_get_context_snippet_no_ellipsis_for_short_text(self) -> None:
        """Should not add ellipsis for short text."""
        result = self._make_result(text="Short")
        item = SearchResultItem(result, search_query="Short")
        snippet = item._get_context_snippet("Short", "Short")
        assert snippet.count("...") == 0

    def test_get_context_snippet_empty_query(self) -> None:
        """Should return truncated text for empty query."""
        result = self._make_result(text="Some text")
        item = SearchResultItem(result, search_query="")
        snippet = item._get_context_snippet("Some text", "")
        assert "Some text" in snippet

    def test_get_context_snippet_match_at_start(self) -> None:
        """Should handle match at the start of text."""
        result = self._make_result(text="Hello world!")
        item = SearchResultItem(result, search_query="Hello")
        snippet = item._get_context_snippet("Hello world!", "Hello")
        assert snippet.startswith("[bold yellow]Hello[/bold yellow]")
        assert not snippet.startswith("...")

    def test_get_context_snippet_match_at_end(self) -> None:
        """Should handle match at the end of text."""
        result = self._make_result(text="Say goodbye")
        item = SearchResultItem(result, search_query="goodbye")
        snippet = item._get_context_snippet("Say goodbye", "goodbye")
        assert snippet.endswith("[bold yellow]goodbye[/bold yellow]")
        assert not snippet.endswith("...")

    def test_get_context_snippet_no_match_found(self) -> None:
        """Should return truncated text if no match found."""
        result = self._make_result(text="Hello world")
        item = SearchResultItem(result, search_query="xyz")
        snippet = item._get_context_snippet("Hello world", "xyz")
        assert "Hello world" in snippet


class TestSearchResultMessage:
    """Tests for SearchResult model."""

    def test_message_sender_name_from_contact(self) -> None:
        """Should use contact name for sender."""
        from iuselinux.tui.models import Contact

        contact = Contact(handle="test@example.com", name="John Doe")
        msg = Message(
            rowid=1,
            guid="test-guid",
            text="Hello",
            timestamp=datetime.now(),
            is_from_me=False,
            handle_id="test@example.com",
            chat_id=1,
            contact=contact,
        )
        assert msg.sender_name == "John Doe"

    def test_message_sender_name_is_me(self) -> None:
        """Should return 'Me' for outgoing messages."""
        msg = Message(
            rowid=1,
            guid="test-guid",
            text="Hello",
            timestamp=datetime.now(),
            is_from_me=True,
            handle_id="test@example.com",
            chat_id=1,
        )
        assert msg.sender_name == "Me"

    def test_message_sender_name_fallback_to_handle(self) -> None:
        """Should fallback to handle_id when no contact."""
        msg = Message(
            rowid=1,
            guid="test-guid",
            text="Hello",
            timestamp=datetime.now(),
            is_from_me=False,
            handle_id="test@example.com",
            chat_id=1,
        )
        assert msg.sender_name == "test@example.com"
