"""Tests for the compose screen."""

import pytest

from iuselinux.tui.screens.compose import (
    normalize_recipient,
    validate_recipient,
)


class TestValidateRecipient:
    """Tests for validate_recipient function."""

    def test_empty_string_is_invalid(self) -> None:
        """Empty string should return an error."""
        error = validate_recipient("")
        assert error == "Recipient is required"

    def test_whitespace_only_is_invalid(self) -> None:
        """Whitespace only should return an error."""
        error = validate_recipient("   ")
        assert error == "Recipient is required"

    def test_valid_us_phone_number(self) -> None:
        """US phone number should be valid."""
        assert validate_recipient("+15551234567") is None

    def test_valid_phone_without_plus(self) -> None:
        """Phone number without plus should be valid."""
        assert validate_recipient("15551234567") is None

    def test_valid_phone_with_formatting(self) -> None:
        """Phone number with formatting should be valid."""
        assert validate_recipient("+1 (555) 123-4567") is None

    def test_valid_international_phone(self) -> None:
        """International phone number should be valid."""
        assert validate_recipient("+447911123456") is None

    def test_valid_email(self) -> None:
        """Email address should be valid."""
        assert validate_recipient("user@example.com") is None

    def test_valid_email_with_subdomain(self) -> None:
        """Email with subdomain should be valid."""
        assert validate_recipient("user@mail.example.com") is None

    def test_valid_email_with_plus(self) -> None:
        """Email with plus addressing should be valid."""
        assert validate_recipient("user+tag@example.com") is None

    def test_invalid_short_phone(self) -> None:
        """Too short phone number should be invalid."""
        error = validate_recipient("123456")
        assert error == "Enter a valid phone number or email"

    def test_invalid_email_no_at(self) -> None:
        """Email without @ should be invalid."""
        error = validate_recipient("userexample.com")
        assert error == "Enter a valid phone number or email"

    def test_invalid_email_no_domain(self) -> None:
        """Email without domain should be invalid."""
        error = validate_recipient("user@")
        assert error == "Enter a valid phone number or email"

    def test_invalid_random_text(self) -> None:
        """Random text should be invalid."""
        error = validate_recipient("hello world")
        assert error == "Enter a valid phone number or email"


class TestNormalizeRecipient:
    """Tests for normalize_recipient function."""

    def test_strips_whitespace(self) -> None:
        """Should strip leading/trailing whitespace."""
        assert normalize_recipient("  +15551234567  ") == "+15551234567"

    def test_removes_phone_formatting(self) -> None:
        """Should remove phone formatting characters (spaces, dashes, parens)."""
        assert normalize_recipient("+1 (555) 123-4567") == "+15551234567"

    def test_keeps_plus_in_phone(self) -> None:
        """Should keep plus sign in phone number (API accepts it)."""
        assert normalize_recipient("+15551234567") == "+15551234567"

    def test_keeps_email_as_is(self) -> None:
        """Should keep email addresses unchanged."""
        assert normalize_recipient("user@example.com") == "user@example.com"

    def test_keeps_email_case(self) -> None:
        """Should preserve email case."""
        assert normalize_recipient("User@Example.COM") == "User@Example.COM"
