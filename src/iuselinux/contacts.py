"""Contact resolution using macOS AddressBook SQLite database.

This module reads directly from the AddressBook database, which is accessible
via Full Disk Access (the same permission needed for the iMessage database).
No separate Contacts permission is required.
"""

import base64
import logging
import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("iuselinux.contacts")


def _find_addressbook_db() -> Path | None:
    """Find the AddressBook database file."""
    ab_dir = Path.home() / "Library" / "Application Support" / "AddressBook" / "Sources"
    if not ab_dir.exists():
        return None

    # Find the first source directory with an AddressBook database
    for source_dir in ab_dir.iterdir():
        if source_dir.is_dir():
            db_path = source_dir / "AddressBook-v22.abcddb"
            if db_path.exists():
                return db_path
    return None


# Cache the database path
_ADDRESSBOOK_DB: Path | None = None


def _get_db_path() -> Path | None:
    """Get the AddressBook database path, caching the result."""
    global _ADDRESSBOOK_DB
    if _ADDRESSBOOK_DB is None:
        _ADDRESSBOOK_DB = _find_addressbook_db()
    return _ADDRESSBOOK_DB


@dataclass
class ContactInfo:
    """Contact information resolved from a phone number or email."""

    handle: str
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    nickname: str | None = None
    initials: str | None = None
    has_image: bool = False
    image_base64: str | None = None


def _normalize_phone(phone: str) -> str:
    """Extract just the digits from a phone number."""
    return re.sub(r"\D", "", phone)


def _compute_initials(given_name: str | None, family_name: str | None, nickname: str | None) -> str | None:
    """Compute initials from name components."""
    if nickname:
        return nickname[0].upper()

    first_initial = given_name[0].upper() if given_name else ""
    last_initial = family_name[0].upper() if family_name else ""

    combined = first_initial + last_initial
    return combined if combined else None


def _compute_full_name(given_name: str | None, family_name: str | None) -> str | None:
    """Compute full name from components."""
    parts = [p for p in [given_name, family_name] if p]
    return " ".join(parts) if parts else None


def _get_external_data_dir() -> Path | None:
    """Get the _EXTERNAL_DATA directory for contact images."""
    db_path = _get_db_path()
    if not db_path:
        return None
    # _EXTERNAL_DATA is at: Sources/<uuid>/.AddressBook-v22_SUPPORT/_EXTERNAL_DATA/
    external_dir = db_path.parent / ".AddressBook-v22_SUPPORT" / "_EXTERNAL_DATA"
    return external_dir if external_dir.exists() else None


def _extract_image_data(thumbnail_data: bytes | None) -> tuple[bool, str | None]:
    """
    Extract image data from ZTHUMBNAILIMAGEDATA.

    The thumbnail data uses a prefix byte to indicate storage format:
    - 0x01: Inline JPEG data (remaining bytes are the JPEG)
    - 0x02: UUID reference to external file in _EXTERNAL_DATA directory

    Returns:
        Tuple of (has_image, image_base64)
    """
    if not thumbnail_data or len(thumbnail_data) < 2:
        return False, None

    prefix = thumbnail_data[0]

    if prefix == 0x01:
        # Inline JPEG data - skip the 1-byte prefix
        return True, base64.b64encode(thumbnail_data[1:]).decode("ascii")
    elif prefix == 0x02:
        # UUID reference to external file
        # Strip null terminator if present
        uuid_ref = thumbnail_data[1:].decode("ascii", errors="ignore").rstrip("\x00")
        external_dir = _get_external_data_dir()
        if external_dir:
            image_path = external_dir / uuid_ref
            if image_path.exists():
                try:
                    image_data = image_path.read_bytes()
                    return True, base64.b64encode(image_data).decode("ascii")
                except (OSError, IOError) as e:
                    logger.warning("Failed to read external image %s: %s", uuid_ref, e)
        return False, None
    else:
        # Unknown prefix - try treating as inline data (legacy format)
        logger.debug("Unknown thumbnail prefix: 0x%02x", prefix)
        return False, None


def _lookup_by_phone(conn: sqlite3.Connection, phone: str) -> ContactInfo | None:
    """Look up a contact by phone number."""
    normalized = _normalize_phone(phone)
    if not normalized:
        return None

    # Query for contacts with matching phone numbers
    # Match by suffix to handle country code differences
    # Also fetch ZTHUMBNAILIMAGEDATA directly from ZABCDRECORD
    cursor = conn.execute(
        """
        SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, r.Z_PK, r.ZTHUMBNAILIMAGEDATA
        FROM ZABCDRECORD r
        JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK
        WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(p.ZFULLNUMBER, ' ', ''), '-', ''), '(', ''), ')', ''), '+', '') LIKE ?
           OR ? LIKE '%' || REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(p.ZFULLNUMBER, ' ', ''), '-', ''), '(', ''), ')', ''), '+', '')
        LIMIT 1
        """,
        (f"%{normalized}", normalized),
    )
    row = cursor.fetchone()
    if not row:
        return None

    given_name, family_name, nickname, record_pk, thumbnail_data = row

    # Extract image data (handles both inline and external storage)
    has_image, image_base64 = _extract_image_data(thumbnail_data)

    return ContactInfo(
        handle=phone,
        name=_compute_full_name(given_name, family_name),
        given_name=given_name or None,
        family_name=family_name or None,
        nickname=nickname or None,
        initials=_compute_initials(given_name, family_name, nickname),
        has_image=has_image,
        image_base64=image_base64,
    )


def _lookup_by_email(conn: sqlite3.Connection, email: str) -> ContactInfo | None:
    """Look up a contact by email address."""
    cursor = conn.execute(
        """
        SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, r.Z_PK, r.ZTHUMBNAILIMAGEDATA
        FROM ZABCDRECORD r
        JOIN ZABCDEMAILADDRESS e ON e.ZOWNER = r.Z_PK
        WHERE LOWER(e.ZADDRESS) = LOWER(?)
        LIMIT 1
        """,
        (email,),
    )
    row = cursor.fetchone()
    if not row:
        return None

    given_name, family_name, nickname, record_pk, thumbnail_data = row

    # Extract image data (handles both inline and external storage)
    has_image, image_base64 = _extract_image_data(thumbnail_data)

    return ContactInfo(
        handle=email,
        name=_compute_full_name(given_name, family_name),
        given_name=given_name or None,
        family_name=family_name or None,
        nickname=nickname or None,
        initials=_compute_initials(given_name, family_name, nickname),
        has_image=has_image,
        image_base64=image_base64,
    )


@lru_cache(maxsize=1024)
def resolve_contact(handle: str) -> ContactInfo:
    """
    Resolve a phone number or email to contact information.

    Reads directly from the macOS AddressBook SQLite database.
    Results are cached in memory for performance.

    Args:
        handle: Phone number (e.g., "+15551234567") or email address

    Returns:
        ContactInfo with resolved name, initials, etc. or just the handle
        if no match is found or the database is unavailable.
    """
    db_path = _get_db_path()
    if not db_path:
        logger.debug("AddressBook database not found")
        return ContactInfo(handle=handle)

    logger.debug("Resolving contact: %s", handle)
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            if "@" in handle:
                result = _lookup_by_email(conn, handle)
            else:
                result = _lookup_by_phone(conn, handle)

            if result:
                logger.debug("Resolved %s -> %s", handle, result.name)
                return result
            else:
                logger.debug("Contact not found: %s", handle)
                return ContactInfo(handle=handle)
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("AddressBook database error: %s", e)
        return ContactInfo(handle=handle)


def clear_cache() -> None:
    """Clear the contact resolution cache."""
    resolve_contact.cache_clear()
    # Also reset the DB path cache in case it changed
    global _ADDRESSBOOK_DB
    _ADDRESSBOOK_DB = None


def is_available() -> bool:
    """Check if contact resolution is available (database exists)."""
    return _get_db_path() is not None
