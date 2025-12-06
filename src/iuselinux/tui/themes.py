"""Theme support for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ThemeMode(Enum):
    """Theme mode options."""

    DARK = "dark"
    LIGHT = "light"
    AUTO = "auto"


@dataclass
class ThemeColors:
    """Color definitions for a theme."""

    primary: str
    secondary: str
    accent: str
    background: str
    surface: str
    text: str
    text_muted: str
    success: str
    warning: str
    error: str


# iMessage-inspired themes
DARK_THEME = ThemeColors(
    primary="#0b84fe",  # iMessage blue
    secondary="#34c759",  # iOS green
    accent="#5ac8fa",  # Light blue accent
    background="#000000",
    surface="#1c1c1e",
    text="#ffffff",
    text_muted="#8e8e93",
    success="#34c759",
    warning="#ff9f0a",
    error="#ff3b30",
)

LIGHT_THEME = ThemeColors(
    primary="#007aff",  # iMessage blue (light mode)
    secondary="#34c759",
    accent="#5ac8fa",
    background="#ffffff",
    surface="#f2f2f7",
    text="#000000",
    text_muted="#8e8e93",
    success="#34c759",
    warning="#ff9500",
    error="#ff3b30",
)


def get_theme(mode: ThemeMode, system_dark: bool = True) -> ThemeColors:
    """Get the theme colors for a given mode.

    Args:
        mode: The theme mode to use
        system_dark: Whether the system is in dark mode (for auto mode)

    Returns:
        The appropriate theme colors
    """
    if mode == ThemeMode.DARK:
        return DARK_THEME
    elif mode == ThemeMode.LIGHT:
        return LIGHT_THEME
    else:  # AUTO
        return DARK_THEME if system_dark else LIGHT_THEME


def detect_system_dark_mode() -> bool:
    """Detect if the system is in dark mode.

    Returns True for dark mode, False for light mode.
    Defaults to True if detection fails.
    """
    import subprocess
    import sys

    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            return result.stdout.strip().lower() == "dark"
        except Exception:
            return True  # Default to dark
    else:
        # On Linux/other, default to dark
        return True
