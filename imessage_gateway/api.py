"""FastAPI server for iMessage Gateway."""

import re
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator


# Rate limiting for send endpoint
RATE_LIMIT_MESSAGES = 10  # Max messages per window
RATE_LIMIT_WINDOW = 60  # Window in seconds
_send_timestamps: deque[float] = deque()

from .db import FullDiskAccessError, check_db_access
from .messages import get_chats, get_messages, Chat, Message
from .sender import send_imessage, SendResult

app = FastAPI(
    title="iMessage Gateway",
    description="Read and send iMessages via local API",
    version="0.1.0",
)

# Serve static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.exception_handler(FullDiskAccessError)
async def full_disk_access_handler(request: Request, exc: FullDiskAccessError):
    """Handle missing Full Disk Access permission."""
    return JSONResponse(
        status_code=403,
        content={
            "detail": str(exc),
            "error_type": "full_disk_access_required",
        },
    )


@app.get("/")
def index():
    """Serve the main UI."""
    return FileResponse(static_dir / "index.html")


# Response models
class ChatResponse(BaseModel):
    """Chat/conversation response."""

    rowid: int
    guid: str
    display_name: str | None
    identifier: str | None
    last_message_time: str | None  # ISO format
    participants: list[str] | None = None  # For group chats


class MessageResponse(BaseModel):
    """Message response."""

    rowid: int
    text: str | None
    timestamp: str | None  # ISO format
    is_from_me: bool
    handle_id: str | None
    chat_id: int | None
    tapback_type: str | None = None  # Reaction type: love, like, dislike, laugh, emphasize, question
    associated_guid: str | None = None  # GUID of message this reacts to


# Validation patterns
PHONE_PATTERN = re.compile(r"^\+?[1-9]\d{6,14}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_MESSAGE_LENGTH = 10000


class SendRequest(BaseModel):
    """Request to send a message."""

    recipient: str = Field(..., min_length=1, max_length=320)
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LENGTH)

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, v: str) -> str:
        v = v.strip()
        # Remove common phone formatting
        normalized = re.sub(r"[\s\-\(\)]", "", v)
        if PHONE_PATTERN.match(normalized):
            return normalized
        if EMAIL_PATTERN.match(v):
            return v
        raise ValueError("recipient must be a valid phone number or email")

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be empty or whitespace only")
        return v


class SendResponse(BaseModel):
    """Response from sending a message."""

    success: bool
    error: str | None = None


def _chat_to_response(chat: Chat) -> ChatResponse:
    """Convert Chat dataclass to response model."""
    return ChatResponse(
        rowid=chat.rowid,
        guid=chat.guid,
        display_name=chat.display_name,
        identifier=chat.identifier,
        last_message_time=chat.last_message_time.isoformat() if chat.last_message_time else None,
        participants=chat.participants,
    )


def _message_to_response(msg: Message) -> MessageResponse:
    """Convert Message dataclass to response model."""
    return MessageResponse(
        rowid=msg.rowid,
        text=msg.text,
        timestamp=msg.timestamp.isoformat() if msg.timestamp else None,
        is_from_me=msg.is_from_me,
        handle_id=msg.handle_id,
        chat_id=msg.chat_id,
        tapback_type=msg.tapback_type,
        associated_guid=msg.associated_guid,
    )


@app.get("/chats", response_model=list[ChatResponse])
def list_chats(limit: int = Query(default=100, le=500)) -> list[ChatResponse]:
    """List all chats/conversations."""
    chats = get_chats(limit=limit)
    return [_chat_to_response(c) for c in chats]


@app.get("/messages", response_model=list[MessageResponse])
def list_messages(
    chat_id: int | None = Query(default=None, description="Filter to specific chat"),
    limit: int = Query(default=50, le=500),
    after_rowid: int | None = Query(default=None, description="Only messages after this rowid"),
) -> list[MessageResponse]:
    """Fetch messages, optionally filtered by chat."""
    messages = get_messages(chat_id=chat_id, limit=limit, after_rowid=after_rowid)
    return [_message_to_response(m) for m in messages]


def _check_rate_limit() -> None:
    """Check and enforce rate limit, raises HTTPException if exceeded."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW

    # Remove old timestamps
    while _send_timestamps and _send_timestamps[0] < cutoff:
        _send_timestamps.popleft()

    if len(_send_timestamps) >= RATE_LIMIT_MESSAGES:
        retry_after = int(_send_timestamps[0] - cutoff) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT_MESSAGES} messages per {RATE_LIMIT_WINDOW}s",
            headers={"Retry-After": str(retry_after)},
        )


@app.post("/send", response_model=SendResponse)
def send_message(request: SendRequest) -> SendResponse:
    """Send an iMessage."""
    _check_rate_limit()

    result = send_imessage(request.recipient, request.message)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    _send_timestamps.append(time.time())
    return SendResponse(success=True)


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint with database access status."""
    db_ok = check_db_access()
    return {
        "status": "ok" if db_ok else "degraded",
        "database_accessible": db_ok,
    }
