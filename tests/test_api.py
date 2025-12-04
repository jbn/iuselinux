"""Tests for API endpoints."""

from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from imessage_gateway.api import app, _classify_send_error, SendErrorType
from imessage_gateway.messages import Chat, Message, Attachment
from imessage_gateway.contacts import ContactInfo
from imessage_gateway.sender import SendResult


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
        with patch("imessage_gateway.api.check_db_access", return_value=True), \
             patch("imessage_gateway.api.contacts_available", return_value=True):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["database_accessible"] is True
            assert "ffmpeg_available" in data
            assert "contacts_available" in data

    def test_health_degraded_when_db_unavailable(self, client):
        with patch("imessage_gateway.api.check_db_access", return_value=False), \
             patch("imessage_gateway.api.contacts_available", return_value=False):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "degraded"
            assert data["database_accessible"] is False


class TestChatsEndpoint:
    """Tests for /chats endpoint."""

    def test_list_chats_returns_chats(self, client, mock_chats):
        with patch("imessage_gateway.api.get_chats", return_value=mock_chats), \
             patch("imessage_gateway.api.contacts_available", return_value=False):
            response = client.get("/chats")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["rowid"] == 1
            assert data[0]["display_name"] == "Test Chat 1"

    def test_list_chats_with_limit(self, client, mock_chats):
        with patch("imessage_gateway.api.get_chats", return_value=mock_chats[:1]) as mock_get:
            with patch("imessage_gateway.api.contacts_available", return_value=False):
                response = client.get("/chats?limit=1")
                assert response.status_code == 200
                mock_get.assert_called_once_with(limit=1)


class TestMessagesEndpoint:
    """Tests for /messages endpoint."""

    def test_list_messages_returns_messages(self, client, mock_messages):
        with patch("imessage_gateway.api.get_messages", return_value=mock_messages), \
             patch("imessage_gateway.api.contacts_available", return_value=False):
            response = client.get("/messages?chat_id=1")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["text"] == "Hello, world!"
            assert data[0]["is_from_me"] is True

    def test_list_messages_with_filters(self, client, mock_messages):
        with patch("imessage_gateway.api.get_messages", return_value=mock_messages) as mock_get:
            with patch("imessage_gateway.api.contacts_available", return_value=False):
                response = client.get("/messages?chat_id=1&limit=50&after_rowid=99")
                assert response.status_code == 200
                mock_get.assert_called_once_with(chat_id=1, limit=50, after_rowid=99)


class TestPollEndpoint:
    """Tests for /poll endpoint."""

    def test_poll_returns_messages(self, client, mock_messages):
        with patch("imessage_gateway.api.get_messages", return_value=mock_messages), \
             patch("imessage_gateway.api.contacts_available", return_value=False):
            response = client.get("/poll?after_rowid=50")
            assert response.status_code == 200
            data = response.json()
            assert "messages" in data
            assert "last_rowid" in data
            assert "has_more" in data

    def test_poll_detects_more_messages(self, client, mock_messages):
        # Return limit+1 messages to trigger has_more
        many_messages = mock_messages * 51
        with patch("imessage_gateway.api.get_messages", return_value=many_messages), \
             patch("imessage_gateway.api.contacts_available", return_value=False):
            response = client.get("/poll?after_rowid=0&limit=100")
            assert response.status_code == 200
            data = response.json()
            assert data["has_more"] is True


class TestSendEndpoint:
    """Tests for /send endpoint."""

    def test_send_message_success(self, client):
        with patch("imessage_gateway.api.send_imessage", return_value=SendResult(success=True)):
            response = client.post(
                "/send",
                json={"recipient": "+15551234567", "message": "Test message"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    def test_send_message_failure(self, client):
        with patch("imessage_gateway.api.send_imessage", return_value=SendResult(success=False, error="Can't get buddy")):
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
        with patch("imessage_gateway.api.send_imessage") as mock_send:
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
        with patch("imessage_gateway.api.send_imessage") as mock_send:
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
        with patch("imessage_gateway.api.get_config", return_value={
            "custom_css": "",
            "prevent_sleep": True,
            "vim_bindings": False,
            "api_token": "",
            "contact_cache_ttl": 86400,
            "log_level": "WARNING",
        }):
            response = client.get("/config")
            assert response.status_code == 200
            data = response.json()
            assert "prevent_sleep" in data
            assert "vim_bindings" in data
            assert "log_level" in data

    def test_update_config(self, client):
        with patch("imessage_gateway.api.update_config", return_value={
            "custom_css": "",
            "prevent_sleep": False,
            "vim_bindings": True,
            "api_token": "",
            "contact_cache_ttl": 86400,
            "log_level": "INFO",
        }):
            response = client.put(
                "/config",
                json={"vim_bindings": True, "log_level": "INFO"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["vim_bindings"] is True
            assert data["log_level"] == "INFO"

    def test_get_config_defaults(self, client):
        response = client.get("/config/defaults")
        assert response.status_code == 200
        data = response.json()
        assert "prevent_sleep" in data
        assert data["log_level"] == "WARNING"


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
