"""Tests for API endpoints."""

import pytest

from imessage_gateway.api import _classify_send_error, SendErrorType


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
