"""Test configuration and fixtures."""

import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def disable_auth():
    """Disable API authentication for all tests."""
    def mock_get_config_value(key):
        if key == "api_token":
            return ""  # No auth required
        # Return defaults for other keys
        from iuselinux.config import DEFAULTS
        return DEFAULTS.get(key)

    with patch("iuselinux.api.get_config_value", side_effect=mock_get_config_value):
        yield
