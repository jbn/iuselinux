"""Tests for contact resolution module."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from iuselinux.contacts import (
    resolve_contact,
    clear_cache,
    is_available,
    ContactInfo,
    _normalize_phone,
    _compute_initials,
    _compute_full_name,
)


@pytest.fixture(autouse=True)
def clear_contact_cache():
    """Clear the contact cache before each test."""
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def mock_addressbook_db():
    """Create a mock AddressBook database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".abcddb", delete=False) as f:
        db_path = Path(f.name)

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE ZABCDRECORD (
            Z_PK INTEGER PRIMARY KEY,
            ZFIRSTNAME VARCHAR,
            ZLASTNAME VARCHAR,
            ZNICKNAME VARCHAR,
            ZTHUMBNAILIMAGEDATA BLOB
        )
    """)
    conn.execute("""
        CREATE TABLE ZABCDPHONENUMBER (
            Z_PK INTEGER PRIMARY KEY,
            ZOWNER INTEGER,
            ZFULLNUMBER VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE ZABCDEMAILADDRESS (
            Z_PK INTEGER PRIMARY KEY,
            ZOWNER INTEGER,
            ZADDRESS VARCHAR
        )
    """)

    # Insert test contacts
    # ZTHUMBNAILIMAGEDATA has a 1-byte prefix before the JPEG data
    # X'01' prefix + X'FFD8FFE0' (JPEG magic bytes)
    conn.execute("INSERT INTO ZABCDRECORD (Z_PK, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZTHUMBNAILIMAGEDATA) VALUES (1, 'John', 'Doe', 'JD', X'01FFD8FFE0')")
    conn.execute("INSERT INTO ZABCDPHONENUMBER (ZOWNER, ZFULLNUMBER) VALUES (1, '+1 (555) 123-4567')")
    conn.execute("INSERT INTO ZABCDEMAILADDRESS (ZOWNER, ZADDRESS) VALUES (1, 'john@example.com')")

    conn.execute("INSERT INTO ZABCDRECORD (Z_PK, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZTHUMBNAILIMAGEDATA) VALUES (2, 'Jane', 'Smith', NULL, NULL)")
    conn.execute("INSERT INTO ZABCDPHONENUMBER (ZOWNER, ZFULLNUMBER) VALUES (2, '2025551234')")

    conn.commit()
    conn.close()

    yield db_path

    db_path.unlink()


class TestNormalizePhone:
    """Tests for _normalize_phone function."""

    def test_removes_spaces(self):
        assert _normalize_phone("+1 555 123 4567") == "15551234567"

    def test_removes_dashes(self):
        assert _normalize_phone("555-123-4567") == "5551234567"

    def test_removes_parens(self):
        assert _normalize_phone("(555) 123-4567") == "5551234567"

    def test_removes_plus(self):
        assert _normalize_phone("+15551234567") == "15551234567"

    def test_handles_empty_string(self):
        assert _normalize_phone("") == ""


class TestComputeInitials:
    """Tests for _compute_initials function."""

    def test_uses_nickname_first_letter(self):
        assert _compute_initials("John", "Doe", "JD") == "J"

    def test_uses_first_and_last_name(self):
        assert _compute_initials("John", "Doe", None) == "JD"

    def test_uses_first_name_only(self):
        assert _compute_initials("John", None, None) == "J"

    def test_uses_last_name_only(self):
        assert _compute_initials(None, "Doe", None) == "D"

    def test_returns_none_when_no_names(self):
        assert _compute_initials(None, None, None) is None


class TestComputeFullName:
    """Tests for _compute_full_name function."""

    def test_combines_first_and_last(self):
        assert _compute_full_name("John", "Doe") == "John Doe"

    def test_first_name_only(self):
        assert _compute_full_name("John", None) == "John"

    def test_last_name_only(self):
        assert _compute_full_name(None, "Doe") == "Doe"

    def test_returns_none_when_no_names(self):
        assert _compute_full_name(None, None) is None


class TestResolveContact:
    """Tests for resolve_contact function."""

    def test_returns_handle_only_when_db_missing(self):
        """When database doesn't exist, return just the handle."""
        with patch("iuselinux.contacts._get_db_path", return_value=None):
            result = resolve_contact("+15551234567")
            assert result.handle == "+15551234567"
            assert result.name is None

    def test_returns_handle_only_on_db_error(self):
        """When database errors, return just the handle."""
        with patch("iuselinux.contacts._get_db_path", return_value=Path("/nonexistent/db")):
            result = resolve_contact("+15551234567")
            assert result.handle == "+15551234567"
            assert result.name is None

    def test_resolves_phone_number(self, mock_addressbook_db):
        """Should resolve contact by phone number."""
        with patch("iuselinux.contacts._get_db_path", return_value=mock_addressbook_db):
            result = resolve_contact("+15551234567")
            assert result.name == "John Doe"
            assert result.given_name == "John"
            assert result.family_name == "Doe"
            assert result.nickname == "JD"
            assert result.initials == "J"  # Uses nickname first letter
            assert result.has_image is True

    def test_resolves_phone_without_country_code(self, mock_addressbook_db):
        """Should match phone even without country code."""
        with patch("iuselinux.contacts._get_db_path", return_value=mock_addressbook_db):
            result = resolve_contact("5551234567")
            assert result.name == "John Doe"

    def test_resolves_email(self, mock_addressbook_db):
        """Should resolve contact by email address."""
        with patch("iuselinux.contacts._get_db_path", return_value=mock_addressbook_db):
            result = resolve_contact("john@example.com")
            assert result.name == "John Doe"
            assert result.given_name == "John"

    def test_email_case_insensitive(self, mock_addressbook_db):
        """Email lookup should be case-insensitive."""
        with patch("iuselinux.contacts._get_db_path", return_value=mock_addressbook_db):
            result = resolve_contact("JOHN@EXAMPLE.COM")
            assert result.name == "John Doe"

    def test_returns_handle_for_no_match(self, mock_addressbook_db):
        """When no contact matches, return just the handle."""
        with patch("iuselinux.contacts._get_db_path", return_value=mock_addressbook_db):
            result = resolve_contact("+19999999999")
            assert result.handle == "+19999999999"
            assert result.name is None

    def test_caches_results(self, mock_addressbook_db):
        """Results should be cached."""
        with patch("iuselinux.contacts._get_db_path", return_value=mock_addressbook_db):
            with patch("sqlite3.connect", wraps=sqlite3.connect) as mock_connect:
                result1 = resolve_contact("+15551234567")
                result2 = resolve_contact("+15551234567")

                # Should only connect once
                assert mock_connect.call_count == 1
                assert result1 == result2

    def test_cache_key_is_handle_specific(self, mock_addressbook_db):
        """Different handles should have separate cache entries."""
        with patch("iuselinux.contacts._get_db_path", return_value=mock_addressbook_db):
            result1 = resolve_contact("+15551234567")
            result2 = resolve_contact("john@example.com")

            assert result1.name == "John Doe"
            assert result2.name == "John Doe"
            # Both found, but through different lookups


class TestClearCache:
    """Tests for clear_cache function."""

    def test_clears_cached_results(self, mock_addressbook_db):
        """clear_cache should force new database query on next resolve."""
        with patch("iuselinux.contacts._get_db_path", return_value=mock_addressbook_db):
            with patch("sqlite3.connect", wraps=sqlite3.connect) as mock_connect:
                resolve_contact("+15551234567")
                assert mock_connect.call_count == 1

                clear_cache()

                resolve_contact("+15551234567")
                assert mock_connect.call_count == 2


class TestIsAvailable:
    """Tests for is_available function."""

    def test_returns_true_when_db_exists(self, mock_addressbook_db):
        """Should return True when database exists."""
        with patch("iuselinux.contacts._get_db_path", return_value=mock_addressbook_db):
            clear_cache()  # Reset the db path cache
            assert is_available() is True

    def test_returns_false_when_db_missing(self):
        """Should return False when database doesn't exist."""
        with patch("iuselinux.contacts._find_addressbook_db", return_value=None):
            clear_cache()  # Reset the db path cache
            assert is_available() is False
