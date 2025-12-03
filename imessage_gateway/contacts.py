"""Contact resolution using macOS Contacts framework via Swift helper."""

import json
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


# Path to the Swift contact_lookup binary (bundled with package)
CONTACT_LOOKUP_PATH = Path(__file__).parent / "bin" / "contact_lookup"


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


def _check_binary() -> bool:
    """Check if the contact_lookup binary exists and is executable."""
    return CONTACT_LOOKUP_PATH.exists() and CONTACT_LOOKUP_PATH.is_file()


@lru_cache(maxsize=1024)
def resolve_contact(handle: str) -> ContactInfo:
    """
    Resolve a phone number or email to contact information.

    Uses the Swift contact_lookup binary to query macOS Contacts framework.
    Results are cached in memory for performance.

    Args:
        handle: Phone number (e.g., "+15551234567") or email address

    Returns:
        ContactInfo with resolved name, initials, etc. or just the handle
        if no match is found or the binary is unavailable.
    """
    if not _check_binary():
        return ContactInfo(handle=handle)

    try:
        proc = subprocess.run(
            [str(CONTACT_LOOKUP_PATH), handle],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return ContactInfo(handle=handle)

        data = json.loads(proc.stdout)
        return ContactInfo(
            handle=data.get("handle", handle),
            name=data.get("name"),
            given_name=data.get("givenName"),
            family_name=data.get("familyName"),
            nickname=data.get("nickname"),
            initials=data.get("initials"),
            has_image=data.get("hasImage", False),
            image_base64=data.get("imageBase64"),
        )
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return ContactInfo(handle=handle)


def clear_cache() -> None:
    """Clear the contact resolution cache."""
    resolve_contact.cache_clear()


def is_available() -> bool:
    """Check if contact resolution is available (binary exists)."""
    return _check_binary()
