"""Database access for iMessage chat.db."""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger("iuselinux.db")

# Mac absolute time epoch: 2001-01-01 00:00:00 UTC
MAC_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
MAC_EPOCH_UNIX = int(MAC_EPOCH.timestamp())

# Default chat.db location
DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"


def get_db_path() -> Path:
    """Get the path to chat.db."""
    return DEFAULT_DB_PATH


class FullDiskAccessError(PermissionError):
    """Raised when Full Disk Access permission is missing."""

    def __init__(self, path: Path):
        super().__init__(
            f"Cannot access {path}. "
            "Grant Full Disk Access to Terminal (or your IDE) in "
            "System Settings > Privacy & Security > Full Disk Access"
        )


def check_db_access(db_path: Path | None = None) -> bool:
    """
    Check if we can access the iMessage database.

    Returns:
        True if accessible, False otherwise
    """
    path = db_path or get_db_path()
    if not path.exists():
        return False
    try:
        with open(path, "rb") as f:
            f.read(1)
        return True
    except PermissionError:
        return False


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """
    Get a read-only connection to chat.db.

    Uses URI mode with ?mode=ro to ensure read-only access.

    Raises:
        FileNotFoundError: If chat.db doesn't exist
        FullDiskAccessError: If permission is denied (need Full Disk Access)
    """
    path = db_path or get_db_path()
    if not path.exists():
        logger.error("Database not found: %s", path)
        raise FileNotFoundError(f"chat.db not found at {path}")

    # Check for Full Disk Access permission
    try:
        with open(path, "rb") as f:
            f.read(1)
    except PermissionError:
        logger.error("Permission denied accessing database (need Full Disk Access)")
        raise FullDiskAccessError(path)

    logger.debug("Opening database connection: %s", path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
        logger.debug("Closed database connection")


def mac_absolute_to_datetime(mac_time: int | None) -> datetime | None:
    """
    Convert Mac absolute time (nanoseconds since 2001-01-01) to datetime.

    Args:
        mac_time: Nanoseconds since Mac epoch, or None

    Returns:
        UTC datetime, or None if input was None
    """
    if mac_time is None:
        return None

    # Convert nanoseconds to seconds and add to Mac epoch
    seconds = mac_time / 1_000_000_000
    unix_timestamp = MAC_EPOCH_UNIX + seconds
    return datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)


def datetime_to_mac_absolute(dt: datetime) -> int:
    """
    Convert datetime to Mac absolute time (nanoseconds since 2001-01-01).

    Args:
        dt: datetime to convert (should be timezone-aware)

    Returns:
        Nanoseconds since Mac epoch
    """
    unix_timestamp = dt.timestamp()
    seconds_since_mac_epoch = unix_timestamp - MAC_EPOCH_UNIX
    return int(seconds_since_mac_epoch * 1_000_000_000)


def extract_text_from_attributed_body(data: bytes) -> str | None:
    """
    Extract text from NSAttributedString typedstream blob.

    iMessage stores rich text in attributedBody as a typedstream-encoded
    NSAttributedString. The text field may be NULL when the message contains
    special formatting, mentions, or was edited.

    The typedstream format uses variable-length integer encoding:
    - Values 0-127: single byte literal
    - 0x81 (-127 signed): 2-byte little-endian length follows
    - 0x82 (-126 signed): 4-byte little-endian length follows

    Args:
        data: Raw attributedBody blob from message table

    Returns:
        Extracted text string, or None if extraction fails
    """
    if not data:
        return None

    # Look for NSString marker
    marker = b"NSString"
    idx = data.find(marker)
    if idx == -1:
        return None

    # After NSString there's metadata then: +<length><text> or *<length><text>
    pos = idx + len(marker)

    while pos < len(data) - 2:
        b = data[pos]
        # + (0x2B) or * (0x2A) markers precede the length encoding
        if b in (0x2B, 0x2A):
            length_byte = data[pos + 1]

            # Typedstream variable-length integer encoding (little-endian on macOS)
            if length_byte == 0x81:  # 2-byte little-endian length
                if pos + 4 > len(data):
                    pos += 1
                    continue
                length = int.from_bytes(data[pos + 2 : pos + 4], "little")
                text_start = pos + 4
            elif length_byte == 0x82:  # 4-byte little-endian length
                if pos + 6 > len(data):
                    pos += 1
                    continue
                length = int.from_bytes(data[pos + 2 : pos + 6], "little")
                text_start = pos + 6
            elif length_byte < 0x80:  # Single-byte length (0-127)
                length = length_byte
                text_start = pos + 2
            else:
                # Other tag values, skip
                pos += 1
                continue

            if 0 < length <= 65535 and text_start + length <= len(data):
                try:
                    text = data[text_start : text_start + length].decode("utf-8")
                    if text:
                        return text
                except UnicodeDecodeError:
                    pass
        pos += 1

    return None
