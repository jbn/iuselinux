"""Message and chat query functions."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .db import get_connection, mac_absolute_to_datetime


@dataclass
class Message:
    """A single iMessage."""

    rowid: int
    text: str | None
    timestamp: datetime | None
    is_from_me: bool
    handle_id: str | None  # phone number or email
    chat_id: int | None


@dataclass
class Chat:
    """A chat/conversation."""

    rowid: int
    guid: str
    display_name: str | None
    identifier: str | None  # For 1:1 chats, the phone/email


def get_messages(
    chat_id: int | None = None,
    limit: int = 50,
    after_rowid: int | None = None,
    db_path: Path | None = None,
) -> list[Message]:
    """
    Fetch messages from chat.db.

    Args:
        chat_id: Filter to specific chat (None for all)
        limit: Max messages to return
        after_rowid: Only return messages with ROWID > this (for polling)
        db_path: Override default db path

    Returns:
        List of Message objects, newest first
    """
    with get_connection(db_path) as conn:
        cur = conn.cursor()

        # Base query with handle join
        query = """
        SELECT
            message.ROWID as rowid,
            message.text,
            message.date as mac_time,
            message.is_from_me,
            handle.id as handle_id,
            chat_message_join.chat_id
        FROM message
        LEFT JOIN handle ON message.handle_id = handle.ROWID
        LEFT JOIN chat_message_join ON message.ROWID = chat_message_join.message_id
        """

        conditions = []
        params: list = []

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

        messages = []
        for row in cur.fetchall():
            messages.append(
                Message(
                    rowid=row["rowid"],
                    text=row["text"],
                    timestamp=mac_absolute_to_datetime(row["mac_time"]),
                    is_from_me=bool(row["is_from_me"]),
                    handle_id=row["handle_id"],
                    chat_id=row["chat_id"],
                )
            )

        return messages


def get_chats(limit: int = 100, db_path: Path | None = None) -> list[Chat]:
    """
    List all chats/conversations.

    Args:
        limit: Max chats to return
        db_path: Override default db path

    Returns:
        List of Chat objects
    """
    with get_connection(db_path) as conn:
        cur = conn.cursor()

        # Get chats with their primary identifier (for 1:1 chats)
        query = """
        SELECT
            chat.ROWID as rowid,
            chat.guid,
            chat.display_name,
            chat.chat_identifier as identifier
        FROM chat
        ORDER BY chat.ROWID DESC
        LIMIT ?
        """

        cur.execute(query, (limit,))

        chats = []
        for row in cur.fetchall():
            chats.append(
                Chat(
                    rowid=row["rowid"],
                    guid=row["guid"],
                    display_name=row["display_name"],
                    identifier=row["identifier"],
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
