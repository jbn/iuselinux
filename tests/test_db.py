"""Tests for database utilities."""

import pytest

from iuselinux.db import extract_text_from_attributed_body


class TestExtractTextFromAttributedBody:
    """Tests for extracting text from NSAttributedString typedstream blobs."""

    def test_returns_none_for_none_input(self):
        assert extract_text_from_attributed_body(None) is None

    def test_returns_none_for_empty_bytes(self):
        assert extract_text_from_attributed_body(b"") is None

    def test_returns_none_for_missing_nsstring_marker(self):
        assert extract_text_from_attributed_body(b"random data without marker") is None

    def test_extracts_text_with_plus_marker(self):
        # Real example from iMessage database (truncated)
        # Format: ...NSString...\x01\x94\x84\x01+<length><text>...
        blob = (
            b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12"
            b"NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84"
            b"\x84\x84\x08NSString\x01\x94\x84\x01+\x0bhello world\x86"
        )
        assert extract_text_from_attributed_body(blob) == "hello world"

    def test_extracts_text_with_asterisk_marker(self):
        # Some messages use * (0x2A) instead of + (0x2B)
        blob = (
            b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12"
            b"NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84"
            b"\x84\x84\x08NSString\x01\x94\x84\x01*\x08test msg\x86"
        )
        assert extract_text_from_attributed_body(blob) == "test msg"

    def test_handles_unicode_text(self):
        # Test with emoji and special characters
        text = "hello 👋 world"
        text_bytes = text.encode("utf-8")
        blob = (
            b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12"
            b"NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84"
            b"\x84\x84\x08NSString\x01\x94\x84\x01+"
            + bytes([len(text_bytes)])
            + text_bytes
            + b"\x86"
        )
        assert extract_text_from_attributed_body(blob) == text

    def test_returns_none_for_truncated_blob(self):
        # Blob that starts correctly but is truncated
        blob = b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSString"
        assert extract_text_from_attributed_body(blob) is None

    def test_extracts_text_with_two_byte_length(self):
        # Test 2-byte length encoding (0x81 marker + 2-byte little-endian length)
        # This is used for strings > 127 bytes
        text = "a" * 150  # 150 character string
        text_bytes = text.encode("utf-8")
        length_bytes = len(text_bytes).to_bytes(2, "little")  # 2-byte little-endian
        blob = (
            b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12"
            b"NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84"
            b"\x84\x84\x08NSString\x01\x94\x84\x01+"
            b"\x81"  # 2-byte length marker
            + length_bytes
            + text_bytes
            + b"\x86"
        )
        assert extract_text_from_attributed_body(blob) == text

    def test_extracts_long_message_with_two_byte_length(self):
        # Test realistic longer message that would use 2-byte encoding
        text = "so graceful with your night time putting him down. i know its insanely frustrating sometimes but you're so sweet with him and patient"
        text_bytes = text.encode("utf-8")
        length_bytes = len(text_bytes).to_bytes(2, "little")  # little-endian
        blob = (
            b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12"
            b"NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84"
            b"\x84\x84\x08NSString\x01\x94\x84\x01+"
            b"\x81"  # 2-byte length marker
            + length_bytes
            + text_bytes
            + b"\x86"
        )
        assert extract_text_from_attributed_body(blob) == text
