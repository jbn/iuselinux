"""Terminal graphics protocol detection.

Detects support for inline image display in terminal emulators.
Supports detection of:
- Kitty graphics protocol (Kitty, Konsole with Kitty support)
- iTerm2 inline images protocol (iTerm2, WezTerm, Konsole)
- Sixel graphics (mlterm, mintty, xterm with Sixel)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class GraphicsProtocol(Enum):
    """Supported terminal graphics protocols."""

    NONE = "none"
    KITTY = "kitty"
    ITERM2 = "iterm2"
    SIXEL = "sixel"


@dataclass
class TerminalCapabilities:
    """Terminal capabilities for graphics display."""

    graphics_protocol: GraphicsProtocol = GraphicsProtocol.NONE
    terminal_name: str | None = None
    supports_animations: bool = False

    @property
    def supports_images(self) -> bool:
        """Check if the terminal supports inline image display."""
        return self.graphics_protocol != GraphicsProtocol.NONE


# Terminals that support the Kitty graphics protocol
KITTY_TERMINALS = frozenset({"kitty"})

# Terminals that support the iTerm2 inline images protocol
ITERM2_TERMINALS = frozenset(
    {
        "iterm.app",
        "iterm2.app",
        "wezterm",
        "konsole",
    }
)

# Terminals that support Sixel graphics
SIXEL_TERMINALS = frozenset(
    {
        "mlterm",
        "mintty",
        "xterm",  # Only with +sixel compile flag, but we can try
        "foot",
    }
)


def detect_terminal_capabilities() -> TerminalCapabilities:
    """Detect terminal graphics capabilities from environment.

    Detection order (highest priority first):
    1. Kitty (via KITTY_WINDOW_ID or TERM=xterm-kitty)
    2. iTerm2 (via TERM_PROGRAM)
    3. Sixel (via TERM_PROGRAM or TERM)

    Returns:
        TerminalCapabilities with detected protocol and terminal info
    """
    # Check for Kitty first - most reliable detection
    if os.environ.get("KITTY_WINDOW_ID"):
        return TerminalCapabilities(
            graphics_protocol=GraphicsProtocol.KITTY,
            terminal_name="kitty",
            supports_animations=True,  # Kitty supports animated images
        )

    term = os.environ.get("TERM", "").lower()
    if term == "xterm-kitty":
        return TerminalCapabilities(
            graphics_protocol=GraphicsProtocol.KITTY,
            terminal_name="kitty",
            supports_animations=True,
        )

    # Check TERM_PROGRAM for various terminals
    term_program = os.environ.get("TERM_PROGRAM", "").lower()

    # iTerm2 detection
    if term_program in ("iterm.app", "iterm2.app"):
        return TerminalCapabilities(
            graphics_protocol=GraphicsProtocol.ITERM2,
            terminal_name="iterm2",
            supports_animations=True,  # iTerm2 supports GIF animation
        )

    # WezTerm supports iTerm2 protocol
    if term_program == "wezterm":
        return TerminalCapabilities(
            graphics_protocol=GraphicsProtocol.ITERM2,
            terminal_name="wezterm",
            supports_animations=True,
        )

    # Konsole supports iTerm2 protocol
    if term_program == "konsole":
        return TerminalCapabilities(
            graphics_protocol=GraphicsProtocol.ITERM2,
            terminal_name="konsole",
            supports_animations=False,
        )

    # Sixel terminals via TERM_PROGRAM
    if term_program in SIXEL_TERMINALS:
        return TerminalCapabilities(
            graphics_protocol=GraphicsProtocol.SIXEL,
            terminal_name=term_program,
            supports_animations=False,
        )

    # Sixel terminals via TERM
    if term in SIXEL_TERMINALS or term.startswith("mlterm"):
        terminal_name = term.split("-")[0] if "-" in term else term
        return TerminalCapabilities(
            graphics_protocol=GraphicsProtocol.SIXEL,
            terminal_name=terminal_name,
            supports_animations=False,
        )

    # No graphics support detected
    return TerminalCapabilities()


# Cached capabilities (detected once per process)
_cached_capabilities: TerminalCapabilities | None = None


def get_terminal_capabilities(force_refresh: bool = False) -> TerminalCapabilities:
    """Get terminal capabilities, with caching.

    Args:
        force_refresh: If True, re-detect capabilities instead of using cache

    Returns:
        TerminalCapabilities for the current terminal
    """
    global _cached_capabilities
    if _cached_capabilities is None or force_refresh:
        _cached_capabilities = detect_terminal_capabilities()
    return _cached_capabilities
