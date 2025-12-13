"""Configuration management for iuselinux.

Stores configuration in macOS user configuration directory:
~/Library/Application Support/iuselinux/config.json
"""

import json
from pathlib import Path
from typing import Any

# macOS user config directory
CONFIG_DIR = Path.home() / "Library" / "Application Support" / "iuselinux"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Default configuration values
DEFAULTS: dict[str, Any] = {
    "custom_css": "",
    "prevent_sleep": True,  # Keep Mac awake while server is running
    "api_token": "",  # Empty means no authentication required
    "contact_cache_ttl": 86400,  # Contact cache TTL in seconds (default 24 hours)
    "log_level": "WARNING",  # Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL
    "notifications_enabled": True,  # Browser notifications for new messages
    "notification_sound_enabled": True,  # Play sound with notifications
    "use_custom_notification_sound": False,  # Use custom uploaded sound instead of default
    "theme": "auto",  # Theme: "auto" (system preference), "light", or "dark"
    # Advanced settings
    "thumbnail_cache_ttl": 86400,  # Video thumbnail cache TTL in seconds (default 24 hours)
    "thumbnail_timestamp": 3.0,  # Seconds into video for thumbnail extraction
    "websocket_poll_interval": 1.0,  # Seconds between WebSocket database polls
    "pending_message_delay": 5.0,  # Seconds before unconfirmed messages show reduced opacity
    # Auto-update settings
    "auto_update_enabled": True,  # Automatically install updates when available
    "update_check_interval": 86400,  # Seconds between update checks (default 24 hours)
    # Tailscale settings
    "tailscale_serve_enabled": False,  # Enable Tailscale serve when server starts
    "tailscale_serve_port": 1960,  # Port for Tailscale serve (should match server port)
    # Tray settings
    "tray_enabled": True,  # Enable menu bar tray icon (used during service install)
}


def _ensure_config_dir() -> None:
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict[str, Any]:
    """Load configuration from disk, returning defaults if file doesn't exist."""
    if not CONFIG_FILE.exists():
        return DEFAULTS.copy()

    try:
        with open(CONFIG_FILE, "r") as f:
            stored = json.load(f)
            # Merge with defaults to ensure all keys exist
            result = DEFAULTS.copy()
            result.update(stored)
            return result
    except (json.JSONDecodeError, IOError):
        return DEFAULTS.copy()


def _save_config(config: dict[str, Any]) -> None:
    """Save configuration to disk."""
    _ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def get_config() -> dict[str, Any]:
    """Get current configuration."""
    return _load_config()


def get_config_value(key: str) -> Any:
    """Get a single configuration value."""
    config = _load_config()
    return config.get(key, DEFAULTS.get(key))


def set_config_value(key: str, value: Any) -> dict[str, Any]:
    """Set a single configuration value and return updated config."""
    if key not in DEFAULTS:
        raise ValueError(f"Unknown configuration key: {key}")

    config = _load_config()
    config[key] = value
    _save_config(config)
    return config


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    """Update multiple configuration values and return updated config."""
    for key in updates:
        if key not in DEFAULTS:
            raise ValueError(f"Unknown configuration key: {key}")

    config = _load_config()
    config.update(updates)
    _save_config(config)
    return config


def reset_config() -> dict[str, Any]:
    """Reset configuration to defaults."""
    _save_config(DEFAULTS.copy())
    return DEFAULTS.copy()
