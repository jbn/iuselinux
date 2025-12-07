"""Tests for inline image rendering."""

from __future__ import annotations

import base64
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from iuselinux.tui.image_renderer import (
    ImageRenderer,
    KittyRenderer,
    ITerm2Renderer,
    get_renderer,
)
from iuselinux.tui.terminal_graphics import GraphicsProtocol, TerminalCapabilities


class TestImageRenderer:
    """Tests for the base ImageRenderer class."""

    def test_abstract_methods(self) -> None:
        """Test that ImageRenderer is abstract."""
        with pytest.raises(TypeError):
            ImageRenderer()  # type: ignore


class TestKittyRenderer:
    """Tests for the KittyRenderer class."""

    def test_render_from_bytes_produces_escape_sequence(self) -> None:
        """Test that render_from_bytes produces a valid escape sequence."""
        renderer = KittyRenderer()
        # Create a minimal 1x1 PNG image
        png_data = create_test_png()

        result = renderer.render_from_bytes(png_data, max_width=80, max_height=24)

        # Should contain Kitty graphics protocol escape sequence
        assert result.startswith("\x1b_G")
        assert result.endswith("\x1b\\")
        # Should contain base64 encoded data
        assert "a=T" in result  # action=transmit and display

    def test_render_from_bytes_respects_dimensions(self) -> None:
        """Test that dimensions are respected."""
        renderer = KittyRenderer()
        png_data = create_test_png()

        result = renderer.render_from_bytes(png_data, max_width=40, max_height=10)

        # Should contain column/row specifications
        assert "c=" in result or "r=" in result

    def test_chunk_data_splits_large_payloads(self) -> None:
        """Test that large data is chunked properly."""
        renderer = KittyRenderer()
        # Create a larger payload
        large_data = b"x" * 5000
        b64_data = base64.standard_b64encode(large_data).decode("ascii")

        chunks = list(renderer._chunk_payload(b64_data))

        # Should have multiple chunks
        assert len(chunks) > 1
        # First chunk should have m=1 (more data coming)
        assert chunks[0][1] is True  # more flag
        # Last chunk should have m=0 (no more data)
        assert chunks[-1][1] is False


class TestITerm2Renderer:
    """Tests for the ITerm2Renderer class."""

    def test_render_from_bytes_produces_escape_sequence(self) -> None:
        """Test that render_from_bytes produces a valid iTerm2 sequence."""
        renderer = ITerm2Renderer()
        png_data = create_test_png()

        result = renderer.render_from_bytes(png_data, max_width=80, max_height=24)

        # Should contain iTerm2 image protocol escape sequence
        assert result.startswith("\x1b]1337;File=")
        assert result.endswith("\x07")
        # Should contain inline=1
        assert "inline=1" in result

    def test_render_from_bytes_includes_dimensions(self) -> None:
        """Test that dimensions are included."""
        renderer = ITerm2Renderer()
        png_data = create_test_png()

        result = renderer.render_from_bytes(png_data, max_width=40, max_height=10)

        # Should contain width/height
        assert "width=" in result
        assert "height=" in result


class TestGetRenderer:
    """Tests for the get_renderer factory function."""

    def test_returns_kitty_renderer_for_kitty(self) -> None:
        """Test that Kitty protocol returns KittyRenderer."""
        caps = TerminalCapabilities(graphics_protocol=GraphicsProtocol.KITTY)
        renderer = get_renderer(caps)
        assert isinstance(renderer, KittyRenderer)

    def test_returns_iterm2_renderer_for_iterm2(self) -> None:
        """Test that iTerm2 protocol returns ITerm2Renderer."""
        caps = TerminalCapabilities(graphics_protocol=GraphicsProtocol.ITERM2)
        renderer = get_renderer(caps)
        assert isinstance(renderer, ITerm2Renderer)

    def test_returns_none_for_no_graphics(self) -> None:
        """Test that no graphics support returns None."""
        caps = TerminalCapabilities(graphics_protocol=GraphicsProtocol.NONE)
        renderer = get_renderer(caps)
        assert renderer is None

    def test_returns_none_for_sixel(self) -> None:
        """Test that Sixel returns None (not yet implemented)."""
        caps = TerminalCapabilities(graphics_protocol=GraphicsProtocol.SIXEL)
        renderer = get_renderer(caps)
        assert renderer is None


def create_test_png() -> bytes:
    """Create a minimal 1x1 PNG image for testing."""
    # Minimal valid PNG: 1x1 red pixel
    # This is a pre-computed minimal PNG
    return bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D,  # IHDR chunk length
        0x49, 0x48, 0x44, 0x52,  # IHDR
        0x00, 0x00, 0x00, 0x01,  # width = 1
        0x00, 0x00, 0x00, 0x01,  # height = 1
        0x08, 0x02,              # bit depth = 8, color type = 2 (RGB)
        0x00, 0x00, 0x00,        # compression, filter, interlace
        0x90, 0x77, 0x53, 0xDE,  # CRC
        0x00, 0x00, 0x00, 0x0C,  # IDAT chunk length
        0x49, 0x44, 0x41, 0x54,  # IDAT
        0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00, 0x00,
        0x01, 0x01, 0x01, 0x00,
        0x18, 0xDD, 0x8D, 0xB4,  # CRC
        0x00, 0x00, 0x00, 0x00,  # IEND chunk length
        0x49, 0x45, 0x4E, 0x44,  # IEND
        0xAE, 0x42, 0x60, 0x82,  # CRC
    ])
