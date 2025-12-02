"""Database access for iMessage chat.db."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

# Mac absolute time epoch: 2001-01-01 00:00:00 UTC
MAC_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
MAC_EPOCH_UNIX = int(MAC_EPOCH.timestamp())

# Default chat.db location
DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"


def get_db_path() -> Path:
    """Get the path to chat.db."""
    return DEFAULT_DB_PATH


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """
    Get a read-only connection to chat.db.

    Uses URI mode with ?mode=ro to ensure read-only access.
    """
    path = db_path or get_db_path()
    if not path.exists():
        raise FileNotFoundError(f"chat.db not found at {path}")

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


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
