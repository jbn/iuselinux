"""Utilities for attachment handling.

Provides functions to download attachments to temp files
and open them with the system default application.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iuselinux.tui.client import APIClient
    from iuselinux.tui.models import Attachment

logger = logging.getLogger(__name__)

# Cache the temp directory path
_temp_dir: Path | None = None


def get_temp_dir() -> Path:
    """Get or create the temp directory for attachments.

    Returns:
        Path to the temp directory
    """
    global _temp_dir
    if _temp_dir is None or not _temp_dir.exists():
        _temp_dir = Path(tempfile.gettempdir()) / "imessage-tui"
        _temp_dir.mkdir(exist_ok=True)
    return _temp_dir


async def download_attachment_to_temp(
    attachment: Attachment,
    api: APIClient,
) -> Path | None:
    """Download an attachment to a temporary file.

    Args:
        attachment: The attachment to download
        api: The API client to use for downloading

    Returns:
        Path to the downloaded file, or None on error
    """
    try:
        # Download the attachment data
        data = await api.get_attachment(attachment.url)

        # Determine filename
        filename = attachment.filename
        if not filename:
            # Use GUID with extension from mime type
            ext = _get_extension_from_mime(attachment.mime_type)
            filename = f"{attachment.guid}{ext}"

        # Save to temp directory
        temp_dir = get_temp_dir()
        file_path = temp_dir / filename

        # Write the file
        file_path.write_bytes(data)
        logger.debug("Downloaded attachment to %s", file_path)

        return file_path

    except Exception as e:
        logger.error("Failed to download attachment: %s", e)
        return None


def open_file_with_system_app(file_path: Path) -> bool:
    """Open a file with the system default application.

    Args:
        file_path: Path to the file to open

    Returns:
        True if the command was launched successfully, False otherwise
    """
    if not file_path.exists():
        logger.error("File does not exist: %s", file_path)
        return False

    try:
        if sys.platform == "darwin":
            # macOS
            subprocess.Popen(["open", str(file_path)])
        elif sys.platform == "win32":
            # Windows
            subprocess.Popen(["start", "", str(file_path)], shell=True)
        else:
            # Linux and others
            subprocess.Popen(["xdg-open", str(file_path)])

        logger.debug("Opened file with system app: %s", file_path)
        return True

    except Exception as e:
        logger.error("Failed to open file: %s", e)
        return False


def _get_extension_from_mime(mime_type: str | None) -> str:
    """Get file extension from MIME type.

    Args:
        mime_type: The MIME type string

    Returns:
        File extension including the dot (e.g., ".png")
    """
    if not mime_type:
        return ""

    # Common MIME type to extension mapping
    mime_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-msvideo": ".avi",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/x-m4a": ".m4a",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
    }

    return mime_map.get(mime_type.lower(), "")
