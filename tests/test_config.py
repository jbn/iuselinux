"""Tests for configuration management."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from iuselinux.config import (
    get_config,
    get_config_value,
    set_config_value,
    update_config,
    reset_config,
    DEFAULTS,
    CONFIG_FILE,
)


@pytest.fixture
def temp_config_dir(tmp_path):
    """Use a temporary directory for config files during tests."""
    config_dir = tmp_path / "iuselinux"
    config_file = config_dir / "config.json"

    with patch("iuselinux.config.CONFIG_DIR", config_dir), \
         patch("iuselinux.config.CONFIG_FILE", config_file):
        yield config_dir, config_file


class TestGetConfig:
    """Tests for get_config."""

    def test_returns_defaults_when_no_file(self, temp_config_dir):
        config_dir, _ = temp_config_dir
        config = get_config()
        assert config == DEFAULTS

    def test_returns_stored_config(self, temp_config_dir):
        config_dir, config_file = temp_config_dir
        config_dir.mkdir(parents=True)
        stored = {"custom_css": "body { color: red; }", "prevent_sleep": True, "theme": "dark"}
        config_file.write_text(json.dumps(stored))

        config = get_config()
        assert config["custom_css"] == "body { color: red; }"
        assert config["prevent_sleep"] is True

    def test_merges_with_defaults_for_missing_keys(self, temp_config_dir):
        config_dir, config_file = temp_config_dir
        config_dir.mkdir(parents=True)
        # Only store one key
        stored = {"custom_css": "test"}
        config_file.write_text(json.dumps(stored))

        config = get_config()
        assert config["custom_css"] == "test"
        # Other keys should have defaults
        assert config["prevent_sleep"] == DEFAULTS["prevent_sleep"]
        assert config["theme"] == DEFAULTS["theme"]


class TestGetConfigValue:
    """Tests for get_config_value."""

    def test_returns_default_for_missing_key(self, temp_config_dir):
        value = get_config_value("custom_css")
        assert value == DEFAULTS["custom_css"]

    def test_returns_stored_value(self, temp_config_dir):
        config_dir, config_file = temp_config_dir
        config_dir.mkdir(parents=True)
        stored = {"custom_css": "test css", "prevent_sleep": False, "theme": "light"}
        config_file.write_text(json.dumps(stored))

        value = get_config_value("custom_css")
        assert value == "test css"


class TestSetConfigValue:
    """Tests for set_config_value."""

    def test_sets_value_and_creates_file(self, temp_config_dir):
        config_dir, config_file = temp_config_dir

        result = set_config_value("custom_css", "body {}")
        assert result["custom_css"] == "body {}"
        assert config_file.exists()

        stored = json.loads(config_file.read_text())
        assert stored["custom_css"] == "body {}"

    def test_raises_for_unknown_key(self, temp_config_dir):
        with pytest.raises(ValueError) as exc_info:
            set_config_value("unknown_key", "value")
        assert "Unknown configuration key" in str(exc_info.value)


class TestUpdateConfig:
    """Tests for update_config."""

    def test_updates_multiple_values(self, temp_config_dir):
        config_dir, config_file = temp_config_dir

        result = update_config({"custom_css": "test", "prevent_sleep": True})
        assert result["custom_css"] == "test"
        assert result["prevent_sleep"] is True

    def test_raises_for_unknown_key(self, temp_config_dir):
        with pytest.raises(ValueError) as exc_info:
            update_config({"custom_css": "test", "bad_key": "value"})
        assert "Unknown configuration key" in str(exc_info.value)


class TestResetConfig:
    """Tests for reset_config."""

    def test_resets_to_defaults(self, temp_config_dir):
        config_dir, config_file = temp_config_dir

        # Set some custom values first
        set_config_value("custom_css", "custom value")

        # Reset
        result = reset_config()
        assert result == DEFAULTS

        # Verify file was updated
        stored = json.loads(config_file.read_text())
        assert stored == DEFAULTS
