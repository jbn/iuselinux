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

logger = logging.getLogger("imessage_gateway.contacts")


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


def _lookup_by_phone(conn: sqlite3.Connection, phone: str) -> ContactInfo | None:
    """Look up a contact by phone number."""
    normalized = _normalize_phone(phone)
    if not normalized:
        return None

    # Query for contacts with matching phone numbers
    # Match by suffix to handle country code differences
    cursor = conn.execute(
        """
        SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, r.Z_PK
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

    given_name, family_name, nickname, record_pk = row

    # Check for contact image
    image_base64 = None
    has_image = False
    img_cursor = conn.execute(
        """
        SELECT ZDATA FROM ZABCDLIKENESS WHERE ZOWNER = ? LIMIT 1
        """,
        (record_pk,),
    )
    img_row = img_cursor.fetchone()
    if img_row and img_row[0]:
        has_image = True
        image_base64 = base64.b64encode(img_row[0]).decode("ascii")

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
        SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, r.Z_PK
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

    given_name, family_name, nickname, record_pk = row

    # Check for contact image
    image_base64 = None
    has_image = False
    img_cursor = conn.execute(
        """
        SELECT ZDATA FROM ZABCDLIKENESS WHERE ZOWNER = ? LIMIT 1
        """,
        (record_pk,),
    )
    img_row = img_cursor.fetchone()
    if img_row and img_row[0]:
        has_image = True
        image_base64 = base64.b64encode(img_row[0]).decode("ascii")

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
