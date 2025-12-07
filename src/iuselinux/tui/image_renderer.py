"""Inline image rendering for terminal graphics protocols.

Supports:
- Kitty graphics protocol
- iTerm2 inline images protocol
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from collections.abc import Iterator

from iuselinux.tui.terminal_graphics import (
    GraphicsProtocol,
    TerminalCapabilities,
)


class ImageRenderer(ABC):
    """Abstract base class for terminal image renderers."""

    @abstractmethod
    def render_from_bytes(
        self,
        image_data: bytes,
        max_width: int = 80,
        max_height: int = 24,
    ) -> str:
        """Render image data to terminal escape sequence.

        Args:
            image_data: Raw image bytes (PNG, JPEG, etc.)
            max_width: Maximum width in terminal columns
            max_height: Maximum height in terminal rows

        Returns:
            Escape sequence string to display the image
        """
        pass


class KittyRenderer(ImageRenderer):
    """Renderer for Kitty graphics protocol.

    See: https://sw.kovidgoyal.net/kitty/graphics-protocol/
    """

    # Maximum payload size per chunk (4096 bytes is safe)
    CHUNK_SIZE = 4096

    def render_from_bytes(
        self,
        image_data: bytes,
        max_width: int = 80,
        max_height: int = 24,
    ) -> str:
        """Render image using Kitty graphics protocol."""
        # Base64 encode the image data
        b64_data = base64.standard_b64encode(image_data).decode("ascii")

        # Build escape sequence
        # a=T: transmit and display
        # f=100: format is PNG (auto-detect actually)
        # c=N: columns (max width)
        # r=N: rows (max height)
        # t=d: direct transmission (data follows)

        parts = []
        first_chunk = True
        for chunk, more in self._chunk_payload(b64_data):
            if first_chunk:
                # First chunk includes all the control parameters
                header = f"a=T,f=100,c={max_width},r={max_height},t=d"
                if more:
                    header += ",m=1"
                parts.append(f"\x1b_G{header};{chunk}\x1b\\")
                first_chunk = False
            else:
                # Continuation chunks
                m = "1" if more else "0"
                parts.append(f"\x1b_Gm={m};{chunk}\x1b\\")

        return "".join(parts)

    def _chunk_payload(self, b64_data: str) -> Iterator[tuple[str, bool]]:
        """Split base64 data into chunks.

        Yields:
            Tuples of (chunk_data, more_flag)
        """
        offset = 0
        while offset < len(b64_data):
            chunk = b64_data[offset : offset + self.CHUNK_SIZE]
            offset += self.CHUNK_SIZE
            more = offset < len(b64_data)
            yield chunk, more


class ITerm2Renderer(ImageRenderer):
    """Renderer for iTerm2 inline images protocol.

    See: https://iterm2.com/documentation-images.html

    Also supported by WezTerm and Konsole.
    """

    def render_from_bytes(
        self,
        image_data: bytes,
        max_width: int = 80,
        max_height: int = 24,
    ) -> str:
        """Render image using iTerm2 inline images protocol."""
        # Base64 encode the image data
        b64_data = base64.standard_b64encode(image_data).decode("ascii")

        # Build escape sequence
        # inline=1: display inline
        # width=N: max width in cells
        # height=N: max height in cells
        # preserveAspectRatio=1: maintain aspect ratio
        params = [
            "inline=1",
            f"width={max_width}",
            f"height={max_height}",
            "preserveAspectRatio=1",
        ]

        return f"\x1b]1337;File={';'.join(params)}:{b64_data}\x07"


def get_renderer(caps: TerminalCapabilities) -> ImageRenderer | None:
    """Get an appropriate renderer for the terminal capabilities.

    Args:
        caps: Terminal capabilities detected from environment

    Returns:
        An ImageRenderer instance, or None if no graphics support
    """
    if caps.graphics_protocol == GraphicsProtocol.KITTY:
        return KittyRenderer()
    elif caps.graphics_protocol == GraphicsProtocol.ITERM2:
        return ITerm2Renderer()
    # Sixel support could be added here in the future
    return None
