"""Message and chat query functions."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .db import get_connection, mac_absolute_to_datetime, extract_text_from_attributed_body


# Tapback reaction types (associated_message_type values)
TAPBACK_TYPES = {
    2000: "love",      # ❤️
    2001: "like",      # 👍
    2002: "dislike",   # 👎
    2003: "laugh",     # 😂
    2004: "emphasize", # ‼️
    2005: "question",  # ❓
    # 3000-3005: Removal of reactions (we ignore these)
}


@dataclass
class Attachment:
    """An attachment (image, video, file) in a message."""

    rowid: int
    guid: str
    filename: str | None  # Full path like ~/Library/Messages/Attachments/...
    mime_type: str | None
    uti: str | None  # Uniform Type Identifier (e.g., public.heic)
    total_bytes: int
    transfer_name: str | None  # Original filename


@dataclass
class Message:
    """A single iMessage."""

    rowid: int
    guid: str
    text: str | None
    timestamp: datetime | None
    is_from_me: bool
    handle_id: str | None  # phone number or email
    chat_id: int | None
    tapback_type: str | None = None  # Reaction type if this is a tapback
    associated_guid: str | None = None  # GUID of message this reacts to
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class Chat:
    """A chat/conversation."""

    rowid: int
    guid: str
    display_name: str | None
    identifier: str | None  # For 1:1 chats, the phone/email
    last_message_time: datetime | None = None
    participants: list[str] | None = None  # List of phone/email for group chats


def get_attachment(
    attachment_id: int,
    db_path: Path | None = None,
) -> Attachment | None:
    """
    Get a single attachment by ID.

    Args:
        attachment_id: Attachment ROWID
        db_path: Override default db path

    Returns:
        Attachment object or None if not found
    """
    with get_connection(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                ROWID as rowid,
                guid,
                filename,
                mime_type,
                uti,
                total_bytes,
                transfer_name
            FROM attachment
            WHERE ROWID = ?
            """,
            (attachment_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return Attachment(
            rowid=row["rowid"],
            guid=row["guid"],
            filename=row["filename"],
            mime_type=row["mime_type"],
            uti=row["uti"],
            total_bytes=row["total_bytes"] or 0,
            transfer_name=row["transfer_name"],
        )


def get_attachments_for_messages(
    message_ids: list[int],
    db_path: Path | None = None,
) -> dict[int, list[Attachment]]:
    """
    Fetch attachments for a list of message IDs.

    Args:
        message_ids: List of message ROWIDs
        db_path: Override default db path

    Returns:
        Dict mapping message_id -> list of Attachment objects
    """
    if not message_ids:
        return {}

    with get_connection(db_path) as conn:
        cur = conn.cursor()
        placeholders = ",".join("?" * len(message_ids))
        cur.execute(
            f"""
            SELECT
                maj.message_id,
                a.ROWID as rowid,
                a.guid,
                a.filename,
                a.mime_type,
                a.uti,
                a.total_bytes,
                a.transfer_name
            FROM message_attachment_join maj
            JOIN attachment a ON maj.attachment_id = a.ROWID
            WHERE maj.message_id IN ({placeholders})
            """,
            message_ids,
        )

        result: dict[int, list[Attachment]] = {}
        for row in cur.fetchall():
            msg_id = row["message_id"]
            attachment = Attachment(
                rowid=row["rowid"],
                guid=row["guid"],
                filename=row["filename"],
                mime_type=row["mime_type"],
                uti=row["uti"],
                total_bytes=row["total_bytes"] or 0,
                transfer_name=row["transfer_name"],
            )
            if msg_id not in result:
                result[msg_id] = []
            result[msg_id].append(attachment)

        return result


def get_messages(
    chat_id: int | None = None,
    limit: int = 50,
    after_rowid: int | None = None,
    db_path: Path | None = None,
    include_attachments: bool = True,
) -> list[Message]:
    """
    Fetch messages from chat.db.

    Args:
        chat_id: Filter to specific chat (None for all)
        limit: Max messages to return
        after_rowid: Only return messages with ROWID > this (for polling)
        db_path: Override default db path
        include_attachments: Whether to fetch attachment metadata

    Returns:
        List of Message objects, newest first
    """
    with get_connection(db_path) as conn:
        cur = conn.cursor()

        # Base query with handle join
        query = """
        SELECT
            message.ROWID as rowid,
            message.guid,
            message.text,
            message.attributedBody,
            message.date as mac_time,
            message.is_from_me,
            message.associated_message_type,
            message.associated_message_guid,
            message.cache_has_attachments,
            handle.id as handle_id,
            chat_message_join.chat_id
        FROM message
        LEFT JOIN handle ON message.handle_id = handle.ROWID
        LEFT JOIN chat_message_join ON message.ROWID = chat_message_join.message_id
        """

        conditions: list[str] = []
        params: list[int] = []

        if chat_id is not None:
            conditions.append("chat_message_join.chat_id = ?")
            params.append(chat_id)

        if after_rowid is not None:
            conditions.append("message.ROWID > ?")
            params.append(after_rowid)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY message.date DESC LIMIT ?"
        params.append(limit)

        cur.execute(query, params)
        rows = cur.fetchall()

        # Collect message IDs that have attachments
        message_ids_with_attachments = [
            row["rowid"] for row in rows
            if row["cache_has_attachments"]
        ]

    # Fetch attachments in a separate query (outside the connection context)
    attachments_map: dict[int, list[Attachment]] = {}
    if include_attachments and message_ids_with_attachments:
        attachments_map = get_attachments_for_messages(
            message_ids_with_attachments, db_path
        )

    messages = []
    for row in rows:
        # Use text field if available, otherwise extract from attributedBody
        text = row["text"]
        if text is None:
            text = extract_text_from_attributed_body(row["attributedBody"])

        # Check for tapback reaction
        assoc_type = row["associated_message_type"]
        tapback_type = TAPBACK_TYPES.get(assoc_type) if assoc_type else None
        associated_guid = row["associated_message_guid"]

        messages.append(
            Message(
                rowid=row["rowid"],
                guid=row["guid"],
                text=text,
                timestamp=mac_absolute_to_datetime(row["mac_time"]),
                is_from_me=bool(row["is_from_me"]),
                handle_id=row["handle_id"],
                chat_id=row["chat_id"],
                tapback_type=tapback_type,
                associated_guid=associated_guid,
                attachments=attachments_map.get(row["rowid"], []),
            )
        )

    return messages


def get_chats(limit: int = 100, db_path: Path | None = None) -> list[Chat]:
    """
    List all chats/conversations, ordered by most recent message.

    Args:
        limit: Max chats to return
        db_path: Override default db path

    Returns:
        List of Chat objects, most recently active first
    """
    with get_connection(db_path) as conn:
        cur = conn.cursor()

        # Get chats with their primary identifier and last message time
        query = """
        SELECT
            chat.ROWID as rowid,
            chat.guid,
            chat.display_name,
            chat.chat_identifier as identifier,
            MAX(message.date) as last_message_time
        FROM chat
        LEFT JOIN chat_message_join ON chat.ROWID = chat_message_join.chat_id
        LEFT JOIN message ON chat_message_join.message_id = message.ROWID
        GROUP BY chat.ROWID
        ORDER BY last_message_time DESC NULLS LAST
        LIMIT ?
        """

        cur.execute(query, (limit,))
        rows = cur.fetchall()

        # Get all chat IDs for participant lookup
        chat_ids = [row["rowid"] for row in rows]

        # Fetch participants for all chats in one query
        participants_map: dict[int, list[str]] = {}
        if chat_ids:
            placeholders = ",".join("?" * len(chat_ids))
            cur.execute(
                f"""
                SELECT chat_handle_join.chat_id, handle.id
                FROM chat_handle_join
                JOIN handle ON chat_handle_join.handle_id = handle.ROWID
                WHERE chat_handle_join.chat_id IN ({placeholders})
                """,
                chat_ids,
            )
            for prow in cur.fetchall():
                chat_id = prow["chat_id"]
                if chat_id not in participants_map:
                    participants_map[chat_id] = []
                participants_map[chat_id].append(prow["id"])

        chats = []
        for row in rows:
            participants = participants_map.get(row["rowid"])
            chats.append(
                Chat(
                    rowid=row["rowid"],
                    guid=row["guid"],
                    display_name=row["display_name"],
                    identifier=row["identifier"],
                    last_message_time=mac_absolute_to_datetime(row["last_message_time"]),
                    participants=participants,
                )
            )

        return chats


def get_chat_messages(
    chat_id: int,
    limit: int = 50,
    after_rowid: int | None = None,
    db_path: Path | None = None,
) -> list[Message]:
    """
    Get messages for a specific chat.

    Convenience wrapper around get_messages.
    """
    return get_messages(
        chat_id=chat_id, limit=limit, after_rowid=after_rowid, db_path=db_path
    )
