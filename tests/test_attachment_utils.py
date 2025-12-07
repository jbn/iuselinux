"""Tests for attachment utilities."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from iuselinux.tui.attachment_utils import (
    download_attachment_to_temp,
    open_file_with_system_app,
    get_temp_dir,
)
from iuselinux.tui.models import Attachment


@pytest.fixture
def sample_attachment() -> Attachment:
    """Create a sample attachment for testing."""
    return Attachment(
        rowid=1,
        guid="test-guid",
        mime_type="image/png",
        filename="test_image.png",
        total_bytes=1024,
        url="/attachments/1/data",
        thumbnail_url="/attachments/1/thumbnail",
    )


def run_async(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestGetTempDir:
    """Tests for get_temp_dir function."""

    def test_creates_directory(self) -> None:
        """Test that temp directory is created."""
        temp_dir = get_temp_dir()
        assert temp_dir.exists()
        assert temp_dir.is_dir()
        assert "imessage-tui" in str(temp_dir)

    def test_returns_same_directory(self) -> None:
        """Test that same directory is returned on multiple calls."""
        dir1 = get_temp_dir()
        dir2 = get_temp_dir()
        assert dir1 == dir2


class TestDownloadAttachmentToTemp:
    """Tests for download_attachment_to_temp function."""

    def test_downloads_and_saves_file(
        self, sample_attachment: Attachment
    ) -> None:
        """Test that attachment is downloaded and saved."""
        mock_api = AsyncMock()
        mock_api.get_attachment.return_value = b"fake image data"

        result = run_async(download_attachment_to_temp(sample_attachment, mock_api))

        assert result is not None
        assert result.exists()
        assert result.name == "test_image.png"
        assert result.read_bytes() == b"fake image data"

        # Cleanup
        result.unlink()

    def test_uses_guid_for_missing_filename(self) -> None:
        """Test that GUID is used when filename is missing."""
        attachment = Attachment(
            rowid=1,
            guid="abc123",
            mime_type="image/jpeg",
            filename=None,
            total_bytes=512,
            url="/attachments/1/data",
        )
        mock_api = AsyncMock()
        mock_api.get_attachment.return_value = b"data"

        result = run_async(download_attachment_to_temp(attachment, mock_api))

        assert result is not None
        assert "abc123" in result.name

        # Cleanup
        result.unlink()

    def test_returns_none_on_error(
        self, sample_attachment: Attachment
    ) -> None:
        """Test that None is returned on download error."""
        mock_api = AsyncMock()
        mock_api.get_attachment.side_effect = Exception("Network error")

        result = run_async(download_attachment_to_temp(sample_attachment, mock_api))

        assert result is None


class TestOpenFileWithSystemApp:
    """Tests for open_file_with_system_app function."""

    def test_calls_open_on_macos(self, tmp_path: Path) -> None:
        """Test that 'open' command is called on macOS."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        with patch("subprocess.Popen") as mock_popen:
            with patch("sys.platform", "darwin"):
                open_file_with_system_app(test_file)
                mock_popen.assert_called_once()
                args = mock_popen.call_args[0][0]
                assert args[0] == "open"
                assert str(test_file) in args

    def test_calls_xdg_open_on_linux(self, tmp_path: Path) -> None:
        """Test that 'xdg-open' command is called on Linux."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        with patch("subprocess.Popen") as mock_popen:
            with patch("sys.platform", "linux"):
                open_file_with_system_app(test_file)
                mock_popen.assert_called_once()
                args = mock_popen.call_args[0][0]
                assert args[0] == "xdg-open"

    def test_returns_false_for_missing_file(self, tmp_path: Path) -> None:
        """Test that False is returned for non-existent file."""
        missing_file = tmp_path / "missing.txt"

        result = open_file_with_system_app(missing_file)

        assert result is False
