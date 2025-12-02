"""FastAPI server for iMessage Gateway."""

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .messages import get_chats, get_messages, Chat, Message
from .sender import send_imessage, SendResult

app = FastAPI(
    title="iMessage Gateway",
    description="Read and send iMessages via local API",
    version="0.1.0",
)


# Response models
class ChatResponse(BaseModel):
    """Chat/conversation response."""

    rowid: int
    guid: str
    display_name: str | None
    identifier: str | None


class MessageResponse(BaseModel):
    """Message response."""

    rowid: int
    text: str | None
    timestamp: str | None  # ISO format
    is_from_me: bool
    handle_id: str | None
    chat_id: int | None


class SendRequest(BaseModel):
    """Request to send a message."""

    recipient: str
    message: str


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


@app.post("/send", response_model=SendResponse)
def send_message(request: SendRequest) -> SendResponse:
    """Send an iMessage."""
    result = send_imessage(request.recipient, request.message)
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    return SendResponse(success=True)


@app.get("/health")
def health_check() -> dict:
    """Health check endpoint."""
    return {"status": "ok"}
