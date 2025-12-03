"""Tests for contact resolution module."""

import json
from unittest.mock import patch, MagicMock
import subprocess

import pytest

from imessage_gateway.contacts import (
    resolve_contact,
    clear_cache,
    is_available,
    ContactInfo,
    CONTACT_LOOKUP_PATH,
)


@pytest.fixture(autouse=True)
def clear_contact_cache():
    """Clear the contact cache before each test."""
    clear_cache()
    yield
    clear_cache()


class TestResolveContact:
    """Tests for resolve_contact function."""

    def test_returns_handle_only_when_binary_missing(self):
        """When binary doesn't exist, return just the handle."""
        with patch("imessage_gateway.contacts._check_binary", return_value=False):
            result = resolve_contact("+15551234567")
            assert result.handle == "+15551234567"
            assert result.name is None

    def test_returns_handle_only_on_subprocess_error(self):
        """When subprocess fails, return just the handle."""
        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            with patch("subprocess.run", side_effect=OSError("Binary not found")):
                result = resolve_contact("+15551234567")
                assert result.handle == "+15551234567"
                assert result.name is None

    def test_returns_handle_only_on_nonzero_exit(self):
        """When binary exits with error, return just the handle."""
        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            with patch("subprocess.run", return_value=mock_result):
                result = resolve_contact("+15551234567")
                assert result.handle == "+15551234567"
                assert result.name is None

    def test_returns_handle_only_on_invalid_json(self):
        """When binary returns invalid JSON, return just the handle."""
        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "not valid json"
            with patch("subprocess.run", return_value=mock_result):
                result = resolve_contact("+15551234567")
                assert result.handle == "+15551234567"
                assert result.name is None

    def test_parses_successful_lookup(self):
        """When binary returns valid contact, parse all fields."""
        contact_json = json.dumps({
            "handle": "+15551234567",
            "name": "John Doe",
            "givenName": "John",
            "familyName": "Doe",
            "nickname": "JD",
            "initials": "JD",
            "hasImage": True,
            "imageBase64": "abc123",
        })

        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = contact_json
            with patch("subprocess.run", return_value=mock_result):
                result = resolve_contact("+15551234567")

                assert result.handle == "+15551234567"
                assert result.name == "John Doe"
                assert result.given_name == "John"
                assert result.family_name == "Doe"
                assert result.nickname == "JD"
                assert result.initials == "JD"
                assert result.has_image is True
                assert result.image_base64 == "abc123"

    def test_parses_no_match_result(self):
        """When no contact matches, fields should be None."""
        contact_json = json.dumps({
            "handle": "+15551234567",
            "name": None,
            "givenName": None,
            "familyName": None,
            "nickname": None,
            "initials": None,
            "hasImage": False,
            "imageBase64": None,
        })

        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = contact_json
            with patch("subprocess.run", return_value=mock_result):
                result = resolve_contact("+15551234567")

                assert result.handle == "+15551234567"
                assert result.name is None
                assert result.has_image is False

    def test_caches_results(self):
        """Results should be cached to avoid repeated subprocess calls."""
        contact_json = json.dumps({
            "handle": "+15551234567",
            "name": "John Doe",
            "hasImage": False,
        })

        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = contact_json
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                # First call
                result1 = resolve_contact("+15551234567")
                # Second call (should be cached)
                result2 = resolve_contact("+15551234567")

                # Should only call subprocess once
                assert mock_run.call_count == 1
                assert result1 == result2

    def test_cache_key_is_handle_specific(self):
        """Different handles should have separate cache entries."""
        def make_result(handle):
            return json.dumps({
                "handle": handle,
                "name": f"Contact for {handle}",
                "hasImage": False,
            })

        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            mock_result = MagicMock()
            mock_result.returncode = 0

            def side_effect(args, **kwargs):
                handle = args[1]
                mock_result.stdout = make_result(handle)
                return mock_result

            with patch("subprocess.run", side_effect=side_effect) as mock_run:
                result1 = resolve_contact("+15551234567")
                result2 = resolve_contact("test@example.com")

                # Should call subprocess twice (different handles)
                assert mock_run.call_count == 2
                assert result1.name == "Contact for +15551234567"
                assert result2.name == "Contact for test@example.com"

    def test_timeout_returns_handle_only(self):
        """When subprocess times out, return just the handle."""
        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
                result = resolve_contact("+15551234567")
                assert result.handle == "+15551234567"
                assert result.name is None


class TestClearCache:
    """Tests for clear_cache function."""

    def test_clears_cached_results(self):
        """clear_cache should force new subprocess call on next resolve."""
        contact_json = json.dumps({
            "handle": "+15551234567",
            "name": "John Doe",
            "hasImage": False,
        })

        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = contact_json
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                # First call
                resolve_contact("+15551234567")
                assert mock_run.call_count == 1

                # Clear cache
                clear_cache()

                # Second call should hit subprocess again
                resolve_contact("+15551234567")
                assert mock_run.call_count == 2


class TestIsAvailable:
    """Tests for is_available function."""

    def test_returns_true_when_binary_exists(self):
        """Should return True when binary exists."""
        with patch("imessage_gateway.contacts._check_binary", return_value=True):
            assert is_available() is True

    def test_returns_false_when_binary_missing(self):
        """Should return False when binary doesn't exist."""
        with patch("imessage_gateway.contacts._check_binary", return_value=False):
            assert is_available() is False
