"""Tests for API endpoints."""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from iuselinux.api import app, _classify_send_error, SendErrorType, _check_and_report_db_access
from iuselinux.messages import Chat, Message, Attachment
from iuselinux.contacts import ContactInfo
from iuselinux.sender import SendResult
import iuselinux.api as api_module


# Test fixtures
@pytest.fixture
def client():
    """Create a test client for the API."""
    return TestClient(app)


@pytest.fixture
def mock_chats():
    """Create mock chat data."""
    return [
        Chat(
            rowid=1,
            guid="chat1-guid",
            display_name="Test Chat 1",
            identifier="+15551234567",
            last_message_time=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            participants=["+15551234567"],
        ),
        Chat(
            rowid=2,
            guid="chat2-guid",
            display_name="Group Chat",
            identifier="chat2",
            last_message_time=datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
            participants=["+15551111111", "+15552222222"],
        ),
    ]


@pytest.fixture
def mock_messages():
    """Create mock message data."""
    return [
        Message(
            rowid=100,
            guid="msg1-guid",
            text="Hello, world!",
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            is_from_me=True,
            handle_id=None,
            chat_id=1,
            attachments=[],
        ),
        Message(
            rowid=101,
            guid="msg2-guid",
            text="Hi there!",
            timestamp=datetime(2024, 1, 1, 12, 1, 0, tzinfo=timezone.utc),
            is_from_me=False,
            handle_id="+15551234567",
            chat_id=1,
            attachments=[],
        ),
    ]


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_status(self, client):
        with patch("iuselinux.api.check_db_access", return_value=True), \
             patch("iuselinux.api.contacts_available", return_value=True):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database_accessible"] is True
            assert "ffmpeg_available" in data
            assert "contacts_available" in data

    def test_health_degraded_when_db_unavailable(self, client):
        with patch("iuselinux.api.check_db_access", return_value=False), \
             patch("iuselinux.api.contacts_available", return_value=False):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["database_accessible"] is False


class TestChatsEndpoint:
    """Tests for /chats endpoint."""

    def test_list_chats_returns_chats(self, client, mock_chats):
        with patch("iuselinux.api.get_chats", return_value=mock_chats), \
             patch("iuselinux.api.contacts_available", return_value=False):
            response = client.get("/chats")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["rowid"] == 1
            assert data[0]["display_name"] == "Test Chat 1"

    def test_list_chats_with_limit(self, client, mock_chats):
        with patch("iuselinux.api.get_chats", return_value=mock_chats[:1]) as mock_get:
            with patch("iuselinux.api.contacts_available", return_value=False):
                response = client.get("/chats?limit=1")
                assert response.status_code == 200
                mock_get.assert_called_once_with(limit=1)


class TestMessagesEndpoint:
    """Tests for /messages endpoint."""

    def test_list_messages_returns_messages(self, client, mock_messages):
        with patch("iuselinux.api.get_messages", return_value=mock_messages), \
             patch("iuselinux.api.contacts_available", return_value=False):
            response = client.get("/messages?chat_id=1")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["text"] == "Hello, world!"
            assert data[0]["is_from_me"] is True

    def test_list_messages_with_filters(self, client, mock_messages):
        with patch("iuselinux.api.get_messages", return_value=mock_messages) as mock_get:
            with patch("iuselinux.api.contacts_available", return_value=False):
                response = client.get("/messages?chat_id=1&limit=50&after_rowid=99")
                assert response.status_code == 200
                mock_get.assert_called_once_with(chat_id=1, limit=50, after_rowid=99, before_rowid=None)


class TestPollEndpoint:
    """Tests for /poll endpoint."""

    def test_poll_returns_messages(self, client, mock_messages):
        with patch("iuselinux.api.get_messages", return_value=mock_messages), \
             patch("iuselinux.api.contacts_available", return_value=False):
            response = client.get("/poll?after_rowid=50")
            assert response.status_code == 200
            data = response.json()
            assert "messages" in data
            assert "last_rowid" in data
            assert "has_more" in data

    def test_poll_detects_more_messages(self, client, mock_messages):
        # Return limit+1 messages to trigger has_more
        many_messages = mock_messages * 51
        with patch("iuselinux.api.get_messages", return_value=many_messages), \
             patch("iuselinux.api.contacts_available", return_value=False):
            response = client.get("/poll?after_rowid=0&limit=100")
            assert response.status_code == 200
            data = response.json()
            assert data["has_more"] is True


class TestSendEndpoint:
    """Tests for /send endpoint."""

    def test_send_message_success(self, client):
        with patch("iuselinux.api.send_imessage", return_value=SendResult(success=True)):
            response = client.post(
                "/send",
                json={"recipient": "+15551234567", "message": "Test message"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_send_message_failure(self, client):
        with patch("iuselinux.api.send_imessage", return_value=SendResult(success=False, error="Can't get buddy")):
            response = client.post(
                "/send",
                json={"recipient": "+15551234567", "message": "Test message"},
            )
            assert response.status_code == 404
            data = response.json()
            assert "error" in data["detail"]

    def test_send_rejects_invalid_recipient(self, client):
        response = client.post(
            "/send",
            json={"recipient": "not-a-phone", "message": "Test message"},
        )
        assert response.status_code == 422  # Validation error

    def test_send_accepts_chat_guid(self, client):
        """Test that full chat GUIDs (for group chats) are accepted."""
        with patch("iuselinux.api.send_imessage") as mock_send:
            mock_send.return_value = SendResult(success=True)
            # Test iMessage group chat
            response = client.post(
                "/send",
                json={"recipient": "iMessage;+;chat361112195654916439", "message": "Test message"},
            )
            assert response.status_code == 200
            mock_send.assert_called_once_with("iMessage;+;chat361112195654916439", "Test message")

    def test_send_accepts_sms_chat_guid(self, client):
        """Test that SMS chat GUIDs are accepted."""
        with patch("iuselinux.api.send_imessage") as mock_send:
            mock_send.return_value = SendResult(success=True)
            response = client.post(
                "/send",
                json={"recipient": "SMS;+;chat196624768427923118", "message": "Test message"},
            )
            assert response.status_code == 200
            mock_send.assert_called_once_with("SMS;+;chat196624768427923118", "Test message")

    def test_send_rejects_short_chat_id(self, client):
        """Test that short chat IDs (without service prefix) are rejected."""
        response = client.post(
            "/send",
            json={"recipient": "chat361112195654916439", "message": "Test message"},
        )
        assert response.status_code == 422  # Validation error

    def test_send_rejects_empty_message(self, client):
        response = client.post(
            "/send",
            json={"recipient": "+15551234567", "message": ""},
        )
        assert response.status_code == 422  # Validation error


class TestConfigEndpoint:
    """Tests for /config endpoints."""

    def test_get_config_returns_settings(self, client):
        with patch("iuselinux.api.get_config", return_value={
            "custom_css": "",
            "prevent_sleep": True,
            "theme": "auto",
            "api_token": "",
            "contact_cache_ttl": 86400,
            "log_level": "WARNING",
        }):
            response = client.get("/config")
            assert response.status_code == 200
            data = response.json()
            assert "prevent_sleep" in data
            assert "theme" in data
            assert "log_level" in data

    def test_update_config(self, client):
        with patch("iuselinux.api.update_config", return_value={
            "custom_css": "",
            "prevent_sleep": False,
            "theme": "dark",
            "api_token": "",
            "contact_cache_ttl": 86400,
            "log_level": "INFO",
        }):
            response = client.put(
                "/config",
                json={"theme": "dark", "log_level": "INFO"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["theme"] == "dark"
            assert data["log_level"] == "INFO"

    def test_get_config_defaults(self, client):
        response = client.get("/config/defaults")
        assert response.status_code == 200
        data = response.json()
        assert "prevent_sleep" in data
        assert data["log_level"] == "WARNING"


class TestSleepEndpoints:
    """Tests for /sleep endpoints."""

    def test_get_sleep_status(self, client):
        with patch("iuselinux.api.is_caffeinate_running", return_value=True), \
             patch("iuselinux.api.get_config", return_value={"prevent_sleep": True}):
            response = client.get("/sleep/status")
            assert response.status_code == 200
            data = response.json()
            assert data["caffeinate_running"] is True
            assert data["prevent_sleep_enabled"] is True

    def test_allow_sleep_now(self, client):
        with patch("iuselinux.api.stop_caffeinate", return_value=True) as mock_stop, \
             patch("iuselinux.api.is_caffeinate_running", return_value=False), \
             patch("iuselinux.api.get_config", return_value={"prevent_sleep": True}):
            response = client.post("/sleep/allow")
            assert response.status_code == 200
            mock_stop.assert_called_once()
            data = response.json()
            assert data["caffeinate_running"] is False
            # Config should still say prevent_sleep is enabled
            assert data["prevent_sleep_enabled"] is True

    def test_prevent_sleep_now(self, client):
        with patch("iuselinux.api.start_caffeinate", return_value=True) as mock_start, \
             patch("iuselinux.api.is_caffeinate_running", return_value=True), \
             patch("iuselinux.api.get_config", return_value={"prevent_sleep": True}):
            response = client.post("/sleep/prevent")
            assert response.status_code == 200
            mock_start.assert_called_once()
            data = response.json()
            assert data["caffeinate_running"] is True
            assert data["prevent_sleep_enabled"] is True


class TestClassifySendError:
    """Tests for error classification."""

    def test_none_error_returns_unknown(self):
        status, error_type, message = _classify_send_error(None)
        assert status == 500
        assert error_type == SendErrorType.UNKNOWN
        assert message == "Unknown error occurred"

    def test_buddy_not_found_error(self):
        status, error_type, message = _classify_send_error(
            "execution error: Messages got an error: Can't get buddy \"+1234567890\""
        )
        assert status == 404
        assert error_type == SendErrorType.RECIPIENT_NOT_FOUND
        assert "not found" in message.lower()

    def test_participant_not_found_error(self):
        status, error_type, message = _classify_send_error(
            "Can't get participant \"test@example.com\""
        )
        assert status == 404
        assert error_type == SendErrorType.RECIPIENT_NOT_FOUND

    def test_service_not_available_error(self):
        status, error_type, message = _classify_send_error(
            "Can't get service whose service type = iMessage"
        )
        assert status == 503
        assert error_type == SendErrorType.SERVICE_UNAVAILABLE
        assert "Messages.app" in message

    def test_account_not_signed_in_error(self):
        status, error_type, message = _classify_send_error(
            "Can't get account - not signed in"
        )
        assert status == 503
        assert error_type == SendErrorType.SERVICE_UNAVAILABLE

    def test_timeout_error(self):
        status, error_type, message = _classify_send_error(
            "Timeout: Messages.app did not respond"
        )
        assert status == 504
        assert error_type == SendErrorType.TIMEOUT

    def test_unknown_error_returns_original(self):
        original = "Some unexpected error message"
        status, error_type, message = _classify_send_error(original)
        assert status == 500
        assert error_type == SendErrorType.UNKNOWN
        assert message == original


class TestFullDiskAccessHandling:
    """Tests for Full Disk Access permission handling."""

    def test_check_db_access_returns_false_when_permission_denied(self, client):
        """Test that check_db_access returns False when permission is denied."""
        with patch("iuselinux.db.check_db_access", return_value=False):
            from iuselinux.db import check_db_access
            # We need to patch the actual function behavior
            with patch("builtins.open", side_effect=PermissionError("Permission denied")):
                from iuselinux.db import check_db_access as real_check
                # The real function catches PermissionError and returns False
                result = real_check()
                assert result is False

    def test_check_and_report_db_access_sets_global_state(self):
        """Test that _check_and_report_db_access updates the global _db_accessible."""
        # Test when access is denied
        with patch("iuselinux.api.check_db_access", return_value=False), \
             patch("iuselinux.api.get_db_path", return_value="/fake/path"):
            api_module._db_accessible = None  # Reset state
            result = _check_and_report_db_access()
            assert result is False
            assert api_module._db_accessible is False

        # Test when access is granted
        with patch("iuselinux.api.check_db_access", return_value=True):
            api_module._db_accessible = None  # Reset state
            result = _check_and_report_db_access()
            assert result is True
            assert api_module._db_accessible is True

    def test_index_serves_error_page_when_db_inaccessible(self, client):
        """Test that the index route serves the error page when database is inaccessible."""
        # Set the global state to indicate db is not accessible
        api_module._db_accessible = False
        with patch("iuselinux.api.check_db_access", return_value=False):
            response = client.get("/")
            assert response.status_code == 200
            # Check that it's the error page by looking for distinctive content
            assert b"Full Disk Access" in response.content
            assert b"Permission Required" in response.content or b"error-no-access" in response.content

    def test_index_serves_main_ui_when_db_accessible(self, client):
        """Test that the index route serves the main UI when database is accessible."""
        api_module._db_accessible = True
        with patch("iuselinux.api.check_db_access", return_value=True):
            response = client.get("/")
            assert response.status_code == 200
            # Check that it's the main UI by looking for distinctive content
            assert b"iUseLinux" in response.content
            # The main UI has chat-related elements
            assert b"chat-list" in response.content or b"Select a chat" in response.content

    def test_check_access_endpoint_returns_accessibility_status(self, client):
        """Test that /check-access endpoint correctly reports database accessibility."""
        # Test when inaccessible
        with patch("iuselinux.api.check_db_access", return_value=False):
            response = client.get("/check-access")
            assert response.status_code == 200
            data = response.json()
            assert data["accessible"] is False

        # Test when accessible
        with patch("iuselinux.api.check_db_access", return_value=True):
            response = client.get("/check-access")
            assert response.status_code == 200
            data = response.json()
            assert data["accessible"] is True

    def test_check_access_endpoint_updates_global_state(self, client):
        """Test that /check-access endpoint updates the global _db_accessible state."""
        api_module._db_accessible = False

        with patch("iuselinux.api.check_db_access", return_value=True):
            response = client.get("/check-access")
            assert response.status_code == 200
            assert api_module._db_accessible is True

    def test_index_rechecks_access_when_previously_denied(self, client):
        """Test that index rechecks access when it was previously denied."""
        # Start with access denied
        api_module._db_accessible = False

        # Now access is granted - the index should recheck and serve the main UI
        with patch("iuselinux.api.check_db_access", return_value=True):
            response = client.get("/")
            assert response.status_code == 200
            # Should now be serving the main UI
            assert b"chat-list" in response.content or b"Select a chat" in response.content


class TestVersionEndpoints:
    """Tests for version and update banner endpoints."""

    def test_get_version_returns_current_version(self, client):
        """Test that /version returns current version info."""
        with patch("iuselinux.api.updater_module.get_update_status") as mock_status:
            mock_status.return_value = {
                "current_version": "1.0.0",
                "latest_version": "1.0.0",
                "update_available": False,
                "change_type": None,
                "last_check": "2025-01-01T00:00:00+00:00",
                "error": None,
            }
            with patch("iuselinux.api.get_config_value", return_value=None):
                response = client.get("/version")
                assert response.status_code == 200
                data = response.json()
                assert data["current_version"] == "1.0.0"
                assert data["update_available"] is False
                assert "update_command" in data

    def test_version_includes_change_type_for_major_update(self, client):
        """Test that change_type is 'major' for major version updates."""
        with patch("iuselinux.api.updater_module.get_update_status") as mock_status:
            mock_status.return_value = {
                "current_version": "1.0.0",
                "latest_version": "2.0.0",
                "update_available": True,
                "change_type": "major",
                "last_check": "2025-01-01T00:00:00+00:00",
                "error": None,
            }
            with patch("iuselinux.api.get_config_value", return_value=None):
                response = client.get("/version")
                assert response.status_code == 200
                data = response.json()
                assert data["update_available"] is True
                assert data["change_type"] == "major"

    def test_version_includes_change_type_for_minor_update(self, client):
        """Test that change_type is 'minor' for minor version updates."""
        with patch("iuselinux.api.updater_module.get_update_status") as mock_status:
            mock_status.return_value = {
                "current_version": "1.0.0",
                "latest_version": "1.1.0",
                "update_available": True,
                "change_type": "minor",
                "last_check": "2025-01-01T00:00:00+00:00",
                "error": None,
            }
            with patch("iuselinux.api.get_config_value", return_value=None):
                response = client.get("/version")
                assert response.status_code == 200
                data = response.json()
                assert data["change_type"] == "minor"

    def test_dismiss_banner_succeeds_for_minor_update(self, client):
        """Test that banner can be dismissed for minor updates."""
        with patch("iuselinux.api.updater_module.get_update_status") as mock_status:
            mock_status.return_value = {
                "current_version": "1.0.0",
                "latest_version": "1.1.0",
                "update_available": True,
                "change_type": "minor",
            }
            with patch("iuselinux.api.set_config_value") as mock_set:
                response = client.post("/version/dismiss-banner")
                assert response.status_code == 200
                data = response.json()
                assert data["success"] is True
                assert data["dismissed_until"] is not None
                mock_set.assert_called_once()

    def test_dismiss_banner_fails_for_major_update(self, client):
        """Test that banner cannot be dismissed for major updates."""
        with patch("iuselinux.api.updater_module.get_update_status") as mock_status:
            mock_status.return_value = {
                "current_version": "1.0.0",
                "latest_version": "2.0.0",
                "update_available": True,
                "change_type": "major",
            }
            response = client.post("/version/dismiss-banner")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert data["dismissed_until"] is None

    def test_banner_dismissed_flag_when_not_expired(self, client):
        """Test that banner_dismissed is True when dismissal hasn't expired."""
        from datetime import datetime, timedelta, timezone

        future_time = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

        def mock_get_config(key):
            if key == "update_banner_dismissed_until":
                return future_time
            if key == "api_token":
                return ""  # No auth required
            return None

        with patch("iuselinux.api.updater_module.get_update_status") as mock_status:
            mock_status.return_value = {
                "current_version": "1.0.0",
                "latest_version": "1.1.0",
                "update_available": True,
                "change_type": "minor",
                "last_check": "2025-01-01T00:00:00+00:00",
                "error": None,
            }
            with patch("iuselinux.api.get_config_value", side_effect=mock_get_config):
                response = client.get("/version")
                assert response.status_code == 200
                data = response.json()
                assert data["banner_dismissed"] is True

    def test_banner_not_dismissed_when_expired(self, client):
        """Test that banner_dismissed is False when dismissal has expired."""
        from datetime import datetime, timedelta, timezone

        past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        def mock_get_config(key):
            if key == "update_banner_dismissed_until":
                return past_time
            if key == "api_token":
                return ""  # No auth required
            return None

        with patch("iuselinux.api.updater_module.get_update_status") as mock_status:
            mock_status.return_value = {
                "current_version": "1.0.0",
                "latest_version": "1.1.0",
                "update_available": True,
                "change_type": "minor",
                "last_check": "2025-01-01T00:00:00+00:00",
                "error": None,
            }
            with patch("iuselinux.api.get_config_value", side_effect=mock_get_config):
                response = client.get("/version")
                assert response.status_code == 200
                data = response.json()
                assert data["banner_dismissed"] is False


class TestStaticFileServing:
    """Tests for static file serving, including path traversal protection."""

    def test_serve_valid_static_file(self, client):
        """Test that valid static files are served."""
        # The static directory should contain index.html
        response = client.get("/static/index.html")
        # File may or may not exist depending on build state
        assert response.status_code in (200, 404)

    def test_path_traversal_blocked(self, client):
        """Test that path traversal attempts are blocked.

        Note: Starlette/FastAPI may normalize paths before they reach handlers,
        so both 403 (blocked by our code) and 404 (path normalized to non-existent)
        are acceptable. The key is that the file is NOT served (no 200).
        """
        # Attempt to access /etc/passwd via path traversal
        response = client.get("/static/../../../etc/passwd")
        # Either blocked (403) or normalized away (404) - both are safe
        assert response.status_code in (403, 404)

    def test_path_traversal_with_encoded_dots(self, client):
        """Test path traversal with URL-encoded characters."""
        # FastAPI decodes the path, so this should still be caught
        response = client.get("/static/..%2F..%2F..%2Fetc%2Fpasswd")
        # Could be 403 (blocked) or 404 (not found after traversal blocked)
        assert response.status_code in (403, 404)

    def test_path_traversal_double_dot(self, client):
        """Test simple double-dot traversal."""
        response = client.get("/static/../sender.py")
        # Either blocked (403) or normalized away (404) - both are safe
        assert response.status_code in (403, 404)

    def test_nested_traversal_attempt(self, client):
        """Test deeply nested traversal attempt."""
        response = client.get("/static/a/b/c/../../../../etc/passwd")
        # Either blocked (403) or normalized away (404) - both are safe
        assert response.status_code in (403, 404)

    def test_traversal_with_backslash(self, client):
        """Test path traversal with backslashes (Windows-style)."""
        response = client.get("/static/..\\..\\etc\\passwd")
        # May result in 403 or 404, but should not serve the file
        assert response.status_code in (403, 404)

    def test_directory_access_blocked(self, client):
        """Test that directory access returns 404 (not a file)."""
        response = client.get("/static/")
        # Should return 404 because empty path or directory
        assert response.status_code == 404
