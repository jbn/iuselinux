"""Data models for the TUI client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Contact:
    """Contact information."""

    handle: str
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    nickname: str | None = None
    initials: str | None = None
    has_image: bool = False
    image_url: str | None = None

    @property
    def display_name(self) -> str:
        """Get the best display name for this contact."""
        return self.name or self.nickname or self.handle


@dataclass
class Participant:
    """Participant in a group chat."""

    handle: str
    contact: Contact | None = None

    @property
    def display_name(self) -> str:
        """Get the best display name for this participant."""
        if self.contact:
            return self.contact.display_name
        return self.handle


@dataclass
class Attachment:
    """Attachment metadata."""

    rowid: int
    guid: str
    mime_type: str | None
    filename: str | None
    total_bytes: int
    url: str
    thumbnail_url: str | None = None
    stream_url: str | None = None

    @property
    def is_image(self) -> bool:
        """Check if this is an image attachment."""
        if self.mime_type:
            return self.mime_type.startswith("image/")
        if self.filename:
            return self.filename.lower().endswith(
                (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif")
            )
        return False

    @property
    def is_video(self) -> bool:
        """Check if this is a video attachment."""
        if self.mime_type:
            return self.mime_type.startswith("video/")
        if self.filename:
            return self.filename.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))
        return False


@dataclass
class Message:
    """A message in a chat."""

    rowid: int
    guid: str
    text: str | None
    timestamp: datetime | None
    is_from_me: bool
    handle_id: str | None
    chat_id: int | None
    tapback_type: str | None = None
    associated_guid: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    contact: Contact | None = None

    @property
    def display_text(self) -> str:
        """Get display text, with attachment placeholders."""
        parts = []
        if self.text:
            parts.append(self.text)
        for att in self.attachments:
            if att.is_image:
                parts.append(f"[Image: {att.filename or 'image'}]")
            elif att.is_video:
                parts.append(f"[Video: {att.filename or 'video'}]")
            else:
                parts.append(f"[File: {att.filename or 'attachment'}]")
        return "\n".join(parts) if parts else "[Empty message]"

    @property
    def sender_name(self) -> str:
        """Get the sender's display name."""
        if self.is_from_me:
            return "Me"
        if self.contact:
            return self.contact.display_name
        return self.handle_id or "Unknown"


@dataclass
class Chat:
    """A chat/conversation."""

    rowid: int
    guid: str
    display_name: str | None
    identifier: str | None
    last_message_time: datetime | None
    last_message_text: str | None = None
    last_message_is_from_me: bool = False
    participants: list[str] | None = None
    participant_contacts: list[Participant] | None = None
    contact: Contact | None = None

    @property
    def title(self) -> str:
        """Get the best title for this chat."""
        if self.display_name:
            return self.display_name
        if self.contact and self.contact.name:
            return self.contact.name
        if self.participant_contacts:
            names = [p.display_name for p in self.participant_contacts[:3]]
            suffix = "..." if len(self.participant_contacts) > 3 else ""
            return ", ".join(names) + suffix
        if self.participants:
            return ", ".join(self.participants[:3]) + (
                "..." if len(self.participants) > 3 else ""
            )
        return self.identifier or self.guid

    @property
    def preview(self) -> str:
        """Get preview text for the chat list."""
        if not self.last_message_text:
            return ""
        prefix = "You: " if self.last_message_is_from_me else ""
        text = self.last_message_text[:50]
        if len(self.last_message_text) > 50:
            text += "..."
        return prefix + text

    @property
    def is_group(self) -> bool:
        """Check if this is a group chat."""
        return bool(self.participants and len(self.participants) > 1)


@dataclass
class SearchResult:
    """A search result."""

    message: Message
    chat: Chat | None = None


@dataclass
class HealthStatus:
    """Server health status."""

    status: str
    database: bool
    ffmpeg: bool
    contacts: bool
