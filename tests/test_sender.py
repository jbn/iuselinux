"""Tests for sender module, including security tests for AppleScript escaping."""

import pytest
from iuselinux.sender import _escape_applescript_string, _is_chat_guid
from iuselinux.updater import get_version_change_type


class TestEscapeApplescriptString:
    """Tests for AppleScript string escaping to prevent command injection."""

    def test_escapes_backslashes(self):
        """Test that backslashes are properly escaped."""
        assert _escape_applescript_string("a\\b") == "a\\\\b"
        assert _escape_applescript_string("\\\\") == "\\\\\\\\"

    def test_escapes_double_quotes(self):
        """Test that double quotes are properly escaped."""
        assert _escape_applescript_string('say "hello"') == 'say \\"hello\\"'

    def test_escapes_newlines(self):
        """Test that newlines are escaped to prevent command injection."""
        # This is the critical security fix - newlines could break out of string context
        assert _escape_applescript_string("line1\nline2") == "line1\\nline2"

    def test_escapes_carriage_returns(self):
        """Test that carriage returns are escaped."""
        assert _escape_applescript_string("line1\rline2") == "line1\\rline2"

    def test_escapes_tabs(self):
        """Test that tabs are escaped."""
        assert _escape_applescript_string("col1\tcol2") == "col1\\tcol2"

    def test_escapes_combined_control_chars(self):
        """Test that multiple control characters are properly escaped."""
        input_str = "line1\nline2\r\nline3\ttab"
        expected = "line1\\nline2\\r\\nline3\\ttab"
        assert _escape_applescript_string(input_str) == expected

    def test_prevents_command_injection_via_newline(self):
        """Test that the injection attack described in the audit is prevented.

        The attack vector was:
        'Hello"\ntell application "Finder" to delete every file\n--'

        After proper escaping, the newline should not break out of string context.
        """
        malicious_input = 'Hello"\ntell application "Finder" to delete every file\n--'
        escaped = _escape_applescript_string(malicious_input)

        # The escaped output should NOT contain actual newlines
        assert "\n" not in escaped
        # It should contain escaped newlines
        assert "\\n" in escaped
        # Quotes should be escaped
        assert '\\"' in escaped

        expected = 'Hello\\"\\ntell application \\"Finder\\" to delete every file\\n--'
        assert escaped == expected

    def test_complex_injection_attempts(self):
        """Test various injection attempts are properly escaped."""
        # Attempt to close string and execute command
        attack1 = '" & (do shell script "rm -rf /") & "'
        escaped1 = _escape_applescript_string(attack1)
        assert escaped1 == '\\" & (do shell script \\"rm -rf /\\") & \\"'

        # Attempt using newline to break context
        attack2 = 'normal message\n" & (do shell script "malicious") & "'
        escaped2 = _escape_applescript_string(attack2)
        assert "\n" not in escaped2
        assert "\\n" in escaped2

    def test_empty_string(self):
        """Test that empty strings are handled."""
        assert _escape_applescript_string("") == ""

    def test_normal_message_unchanged(self):
        """Test that normal messages without special chars pass through."""
        normal = "Hello, how are you today?"
        assert _escape_applescript_string(normal) == normal

    def test_unicode_preserved(self):
        """Test that unicode characters are preserved."""
        unicode_msg = "Hello 世界! 🎉"
        assert _escape_applescript_string(unicode_msg) == unicode_msg

    def test_escape_order_matters(self):
        """Test that escaping order is correct (backslashes first)."""
        # If quotes were escaped before backslashes, we'd get wrong output
        input_str = '\\"'  # backslash followed by quote
        # Should escape backslash to \\\\ then quote to \\"
        # Result: \\\\\" (escaped backslash + escaped quote)
        expected = '\\\\\\"'
        assert _escape_applescript_string(input_str) == expected


class TestIsChatGuid:
    """Tests for chat GUID detection."""

    def test_imessage_group_chat(self):
        """Test iMessage group chat GUID format."""
        assert _is_chat_guid("iMessage;+;chat361112195654916439") is True

    def test_sms_group_chat(self):
        """Test SMS group chat GUID format."""
        assert _is_chat_guid("SMS;+;chat196624768427923118") is True

    def test_rcs_group_chat(self):
        """Test RCS group chat GUID format."""
        assert _is_chat_guid("RCS;+;chat123456789") is True

    def test_imessage_minus_variant(self):
        """Test iMessage with minus separator."""
        assert _is_chat_guid("iMessage;-;chat123456") is True

    def test_phone_number_not_chat_guid(self):
        """Test that phone numbers are not detected as chat GUIDs."""
        assert _is_chat_guid("+15551234567") is False

    def test_email_not_chat_guid(self):
        """Test that emails are not detected as chat GUIDs."""
        assert _is_chat_guid("test@example.com") is False

    def test_short_chat_id_not_full_guid(self):
        """Test that short chat IDs without service prefix are rejected."""
        assert _is_chat_guid("chat361112195654916439") is False

    def test_invalid_format(self):
        """Test various invalid formats."""
        assert _is_chat_guid("") is False
        assert _is_chat_guid("iMessage") is False
        assert _is_chat_guid("iMessage;+;") is False
        assert _is_chat_guid("Unknown;+;chat123") is False


class TestGetVersionChangeType:
    """Tests for semver version change type detection."""

    def test_major_version_update(self):
        """Test detection of major version update (breaking changes)."""
        assert get_version_change_type("1.0.0", "2.0.0") == "major"
        assert get_version_change_type("0.1.0", "1.0.0") == "major"
        assert get_version_change_type("1.5.3", "2.0.0") == "major"

    def test_minor_version_update(self):
        """Test detection of minor version update (new features)."""
        assert get_version_change_type("1.0.0", "1.1.0") == "minor"
        assert get_version_change_type("1.0.0", "1.5.0") == "minor"
        assert get_version_change_type("2.3.4", "2.4.0") == "minor"

    def test_patch_version_update(self):
        """Test detection of patch version update (bug fixes)."""
        assert get_version_change_type("1.0.0", "1.0.1") == "patch"
        assert get_version_change_type("1.2.3", "1.2.4") == "patch"
        assert get_version_change_type("0.0.1", "0.0.2") == "patch"

    def test_no_update(self):
        """Test that same version returns None."""
        assert get_version_change_type("1.0.0", "1.0.0") is None

    def test_downgrade_returns_none(self):
        """Test that downgrades return None (not an update)."""
        assert get_version_change_type("2.0.0", "1.0.0") is None
        assert get_version_change_type("1.5.0", "1.4.0") is None

    def test_invalid_version_returns_none(self):
        """Test that invalid versions return None."""
        assert get_version_change_type("invalid", "1.0.0") is None
        assert get_version_change_type("1.0.0", "invalid") is None
        assert get_version_change_type("", "") is None

    def test_prerelease_versions(self):
        """Test handling of prerelease versions."""
        # Prerelease to release is a patch/minor depending on base
        assert get_version_change_type("1.0.0a1", "1.0.0") == "patch"
        assert get_version_change_type("1.0.0", "1.0.1a1") == "patch"
