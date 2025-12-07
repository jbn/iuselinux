"""Tests for terminal graphics protocol detection."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from iuselinux.tui.terminal_graphics import (
    GraphicsProtocol,
    TerminalCapabilities,
    detect_terminal_capabilities,
    get_terminal_capabilities,
)


class TestGraphicsProtocol:
    """Tests for the GraphicsProtocol enum."""

    def test_protocol_values(self) -> None:
        """Test that expected protocol values exist."""
        assert GraphicsProtocol.NONE.value == "none"
        assert GraphicsProtocol.KITTY.value == "kitty"
        assert GraphicsProtocol.ITERM2.value == "iterm2"
        assert GraphicsProtocol.SIXEL.value == "sixel"


class TestTerminalCapabilities:
    """Tests for the TerminalCapabilities dataclass."""

    def test_default_capabilities(self) -> None:
        """Test default capabilities."""
        caps = TerminalCapabilities()
        assert caps.graphics_protocol == GraphicsProtocol.NONE
        assert caps.supports_images is False
        assert caps.supports_animations is False
        assert caps.terminal_name is None

    def test_supports_images_with_kitty(self) -> None:
        """Test that Kitty protocol supports images."""
        caps = TerminalCapabilities(graphics_protocol=GraphicsProtocol.KITTY)
        assert caps.supports_images is True

    def test_supports_images_with_iterm2(self) -> None:
        """Test that iTerm2 protocol supports images."""
        caps = TerminalCapabilities(graphics_protocol=GraphicsProtocol.ITERM2)
        assert caps.supports_images is True

    def test_supports_images_with_sixel(self) -> None:
        """Test that Sixel protocol supports images."""
        caps = TerminalCapabilities(graphics_protocol=GraphicsProtocol.SIXEL)
        assert caps.supports_images is True

    def test_no_images_with_none(self) -> None:
        """Test that NONE protocol doesn't support images."""
        caps = TerminalCapabilities(graphics_protocol=GraphicsProtocol.NONE)
        assert caps.supports_images is False


class TestDetectTerminalCapabilities:
    """Tests for detect_terminal_capabilities function."""

    def test_detect_kitty_via_window_id(self) -> None:
        """Test detection of Kitty via KITTY_WINDOW_ID."""
        with patch.dict(os.environ, {"KITTY_WINDOW_ID": "123"}, clear=True):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.KITTY
            assert caps.terminal_name == "kitty"

    def test_detect_kitty_via_term(self) -> None:
        """Test detection of Kitty via TERM."""
        with patch.dict(os.environ, {"TERM": "xterm-kitty"}, clear=True):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.KITTY
            assert caps.terminal_name == "kitty"

    def test_detect_iterm2(self) -> None:
        """Test detection of iTerm2 via TERM_PROGRAM."""
        with patch.dict(os.environ, {"TERM_PROGRAM": "iTerm.app"}, clear=True):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.ITERM2
            assert caps.terminal_name == "iterm2"

    def test_detect_wezterm(self) -> None:
        """Test detection of WezTerm (supports iTerm2 protocol)."""
        with patch.dict(os.environ, {"TERM_PROGRAM": "WezTerm"}, clear=True):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.ITERM2
            assert caps.terminal_name == "wezterm"

    def test_detect_mintty(self) -> None:
        """Test detection of mintty (supports Sixel)."""
        with patch.dict(os.environ, {"TERM_PROGRAM": "mintty"}, clear=True):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.SIXEL
            assert caps.terminal_name == "mintty"

    def test_detect_mlterm(self) -> None:
        """Test detection of mlterm (supports Sixel)."""
        with patch.dict(os.environ, {"TERM": "mlterm"}, clear=True):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.SIXEL
            assert caps.terminal_name == "mlterm"

    def test_detect_unknown_terminal(self) -> None:
        """Test fallback for unknown terminals."""
        with patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=True):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.NONE
            assert caps.terminal_name is None

    def test_detect_no_env_vars(self) -> None:
        """Test fallback when no environment variables set."""
        with patch.dict(os.environ, {}, clear=True):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.NONE

    def test_kitty_priority_over_iterm2(self) -> None:
        """Test that Kitty detection takes priority over iTerm2."""
        with patch.dict(
            os.environ,
            {"KITTY_WINDOW_ID": "123", "TERM_PROGRAM": "iTerm.app"},
            clear=True,
        ):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.KITTY

    def test_detect_konsole(self) -> None:
        """Test detection of Konsole (supports iTerm2 protocol)."""
        with patch.dict(os.environ, {"TERM_PROGRAM": "konsole"}, clear=True):
            caps = detect_terminal_capabilities()
            assert caps.graphics_protocol == GraphicsProtocol.ITERM2
            assert caps.terminal_name == "konsole"


class TestGetTerminalCapabilities:
    """Tests for get_terminal_capabilities with caching."""

    def test_caches_result(self) -> None:
        """Test that capabilities are cached."""
        import iuselinux.tui.terminal_graphics as tg

        # Clear cache
        tg._cached_capabilities = None

        with patch.dict(os.environ, {"KITTY_WINDOW_ID": "123"}, clear=True):
            caps1 = get_terminal_capabilities()
            assert caps1.graphics_protocol == GraphicsProtocol.KITTY

        # Change environment, but cached value should persist
        with patch.dict(os.environ, {"TERM_PROGRAM": "iTerm.app"}, clear=True):
            caps2 = get_terminal_capabilities()
            # Should still be Kitty from cache
            assert caps2.graphics_protocol == GraphicsProtocol.KITTY
            assert caps1 is caps2  # Same object

        # Clean up
        tg._cached_capabilities = None

    def test_force_refresh(self) -> None:
        """Test that force_refresh bypasses cache."""
        import iuselinux.tui.terminal_graphics as tg

        # Clear cache
        tg._cached_capabilities = None

        with patch.dict(os.environ, {"KITTY_WINDOW_ID": "123"}, clear=True):
            caps1 = get_terminal_capabilities()
            assert caps1.graphics_protocol == GraphicsProtocol.KITTY

        # Change environment and force refresh
        with patch.dict(os.environ, {"TERM_PROGRAM": "iTerm.app"}, clear=True):
            caps2 = get_terminal_capabilities(force_refresh=True)
            # Should now be iTerm2
            assert caps2.graphics_protocol == GraphicsProtocol.ITERM2

        # Clean up
        tg._cached_capabilities = None
